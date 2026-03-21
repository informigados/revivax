"""
RevivaX - Carver Module
Módulo de extração de arquivos (File Carving)
"""

import os
import hashlib
import logging
import base64
from pathlib import Path
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
import threading

from .scanner import DiskScanner, ScanResult

logger = logging.getLogger(__name__)

# Mantido alinhado ao scanner para leituras sequenciais mais consistentes
# durante carving em dispositivos/imagens grandes.
CARVER_CHUNK_SIZE = 16 * 1024 * 1024


@dataclass
class CarveResult:
    """Resultado da extração de um arquivo"""
    success: bool
    source_offset: int
    recovered_path: Optional[str]
    original_size: int
    recovered_size: int
    hash_md5: Optional[str]
    hash_sha256: Optional[str]
    error_message: Optional[str] = None
    verification_status: str = "unknown"  # verified, partial, corrupted, unknown


class FileCarver:
    """
    Motor de file carving para extração de arquivos
    """
    
    def __init__(self, output_dir: str = "recovered", read_only: bool = True):
        self.output_dir = Path(output_dir).resolve()
        self.read_only = read_only
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        
        # Cria diretório de saída
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Estatísticas
        self.stats = {
            'files_processed': 0,
            'files_success': 0,
            'files_failed': 0,
            'bytes_recovered': 0,
            'start_time': None,
            'elapsed_time': 0
        }
    
    def stop(self):
        """Para o carving"""
        self._stop_event.set()
    
    def pause(self):
        """Pausa o carving"""
        self._pause_event.clear()
    
    def resume(self):
        """Retoma o carving"""
        self._pause_event.set()
    
    def _check_pause(self):
        """Verifica e aguarda se está pausado"""
        self._pause_event.wait()
    
    def carve_file(self,
                   drive_path: str,
                   scan_result: ScanResult,
                   output_filename: Optional[str] = None,
                   verify: bool = True) -> CarveResult:
        """
        Extrai um único arquivo do drive
        
        Args:
            drive_path: Caminho do drive
            scan_result: Resultado da varredura
            output_filename: Nome do arquivo de saída (opcional)
            verify: Se deve verificar integridade
            
        Returns:
            CarveResult com resultado da extração
        """
        self._check_pause()
        
        if self._stop_event.is_set():
            return CarveResult(
                success=False,
                source_offset=scan_result.offset,
                recovered_path=None,
                original_size=scan_result.size,
                recovered_size=0,
                hash_md5=None,
                hash_sha256=None,
                error_message="Operação cancelada pelo usuário"
            )
        
        # Gera nome de arquivo se não fornecido
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"recovered_{timestamp}_{scan_result.offset}.{scan_result.extension}"
        
        output_path = self.output_dir / output_filename
        
        # Adiciona extensão se não tiver
        if not output_path.suffix:
            output_path = output_path.with_suffix(f".{scan_result.extension}")

        # ── Modo pasta: copia arquivo diretamente do caminho original ─────────
        original_path = (scan_result.metadata or {}).get('original_path')
        if original_path and os.path.isfile(original_path):
            try:
                import shutil
                self.output_dir.mkdir(parents=True, exist_ok=True)  # Garante caminho de escape
                shutil.copy2(original_path, output_path)
                with open(output_path, 'rb') as copied_file:
                    data = copied_file.read()

                md5_val     = hashlib.md5(data).hexdigest()
                sha256_val  = hashlib.sha256(data).hexdigest()
                bytes_read  = len(data)
                v_status    = self._verify_file_integrity(data, scan_result.extension) if len(data) <= 10 * 1024 * 1024 else 'unknown'
                self.stats['files_processed'] += 1
                self.stats['files_success']   += 1
                self.stats['bytes_recovered'] += bytes_read
                logger.info(f"Arquivo copiado (modo pasta): {output_path} ({bytes_read} bytes)")
                return CarveResult(
                    success=True,
                    source_offset=scan_result.offset,
                    recovered_path=str(output_path),
                    original_size=scan_result.size,
                    recovered_size=bytes_read,
                    hash_md5=md5_val,
                    hash_sha256=sha256_val,
                    verification_status=v_status,
                )
            except (PermissionError, OSError) as e:
                logger.error(f"Não foi possível copiar {original_path}: {e}")
                self.stats['files_processed'] += 1
                self.stats['files_failed']    += 1
                return CarveResult(
                    success=False,
                    source_offset=scan_result.offset,
                    recovered_path=None,
                    original_size=scan_result.size,
                    recovered_size=0,
                    hash_md5=None,
                    hash_sha256=None,
                    error_message=f"Sem permissão para copiar: {os.path.basename(original_path)}",
                )

        resident_data_b64 = (scan_result.metadata or {}).get('resident_data_b64')
        if resident_data_b64:
            return self._carve_resident_data(scan_result, output_path, resident_data_b64, verify)

        data_runs = (scan_result.metadata or {}).get('data_runs')
        source_device = (scan_result.metadata or {}).get('source_device')
        cluster_size = int((scan_result.metadata or {}).get('cluster_size') or 0)
        if data_runs and source_device and cluster_size > 0:
            return self._carve_from_data_runs(scan_result, output_path, source_device, data_runs, cluster_size, verify)
        
        try:
            # ── Modo raw device: abre drive e lê bytes no offset ───────────────
            with open(drive_path, 'rb') as drive:
                # Posiciona no offset
                drive.seek(scan_result.offset)
                
                # Lê os dados em chunks para não estourar a RAM
                bytes_read = 0
                md5 = hashlib.md5()
                sha256 = hashlib.sha256()
                
                verification_status = "unknown"
                header_data = b""
                has_header = False
                
                self.output_dir.mkdir(parents=True, exist_ok=True)  # Garante destino
                
                with open(output_path, 'wb') as out_f:
                    while bytes_read < scan_result.size:
                        if self._stop_event.is_set():
                            raise Exception("Operação cancelada pelo usuário")
                        self._check_pause()
                        
                        chunk_to_read = min(CARVER_CHUNK_SIZE, scan_result.size - bytes_read)
                        chunk = drive.read(chunk_to_read)
                        
                        if not chunk:
                            break
                        
                        md5.update(chunk)
                        sha256.update(chunk)
                        
                        if not has_header:
                            header_data = chunk[:1024]
                            has_header = True
                            
                        out_f.write(chunk)
                        bytes_read += len(chunk)

                if bytes_read == 0:
                    output_path.unlink(missing_ok=True)
                    return CarveResult(
                        success=False,
                        source_offset=scan_result.offset,
                        recovered_path=None,
                        original_size=scan_result.size,
                        recovered_size=0,
                        hash_md5=None,
                        hash_sha256=None,
                        error_message="Nenhum dado lido do offset especificado"
                    )
                
                if verify and has_header:
                     # Apenas tenta verificar o header ou delega pra função se o arquivo for bem pequeno.
                    if bytes_read <= 10 * 1024 * 1024:
                        with open(output_path, 'rb') as small_f:
                            verification_status = self._verify_file_integrity(
                                small_f.read(), scan_result.extension
                            )
                    else:
                        verification_status = self._verify_generic(header_data, scan_result.extension)

                hash_md5 = md5.hexdigest()
                hash_sha256 = sha256.hexdigest()
                
                # Atualiza estatísticas
                self.stats['files_processed'] += 1
                self.stats['files_success'] += 1
                self.stats['bytes_recovered'] += bytes_read
                
                logger.info(f"Arquivo recuperado: {output_path} ({bytes_read} bytes)")
                
                return CarveResult(
                    success=True,
                    source_offset=scan_result.offset,
                    recovered_path=str(output_path),
                    original_size=scan_result.size,
                    recovered_size=bytes_read,
                    hash_md5=hash_md5,
                    hash_sha256=hash_sha256,
                    verification_status=verification_status
                )
                
        except PermissionError as e:
            logger.error(f"Permissão negada: {e}")
            self.stats['files_processed'] += 1
            self.stats['files_failed'] += 1
            return CarveResult(
                success=False,
                source_offset=scan_result.offset,
                recovered_path=None,
                original_size=scan_result.size,
                recovered_size=0,
                hash_md5=None,
                hash_sha256=None,
                error_message=f"Permissão negada: {str(e)}"
            )
            
        except Exception as e:
            logger.error(f"Erro ao extrair arquivo: {e}")
            self.stats['files_processed'] += 1
            self.stats['files_failed'] += 1
            return CarveResult(
                success=False,
                source_offset=scan_result.offset,
                recovered_path=None,
                original_size=scan_result.size,
                recovered_size=0,
                hash_md5=None,
                hash_sha256=None,
                error_message=str(e)
            )

    def _carve_resident_data(self, scan_result: ScanResult, output_path: Path, resident_data_b64: str, verify: bool) -> CarveResult:
        try:
            data = base64.b64decode(resident_data_b64.encode('ascii'))
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as out_f:
                out_f.write(data)

            md5_val = hashlib.md5(data).hexdigest()
            sha256_val = hashlib.sha256(data).hexdigest()
            verification_status = self._verify_file_integrity(data, scan_result.extension) if verify else 'unknown'
            self.stats['files_processed'] += 1
            self.stats['files_success'] += 1
            self.stats['bytes_recovered'] += len(data)
            return CarveResult(
                success=True,
                source_offset=scan_result.offset,
                recovered_path=str(output_path),
                original_size=scan_result.size,
                recovered_size=len(data),
                hash_md5=md5_val,
                hash_sha256=sha256_val,
                verification_status=verification_status,
            )
        except Exception as exc:
            logger.error("Erro ao reconstruir resident data NTFS: %s", exc)
            self.stats['files_processed'] += 1
            self.stats['files_failed'] += 1
            return CarveResult(
                success=False,
                source_offset=scan_result.offset,
                recovered_path=None,
                original_size=scan_result.size,
                recovered_size=0,
                hash_md5=None,
                hash_sha256=None,
                error_message=str(exc),
            )

    def _open_source_for_carving(self, source_device: str):
        if os.name == 'nt' and DiskScanner._is_windows_device_path(source_device):
            normalized = source_device
            if len(normalized) == 2 and normalized[1] == ':':
                normalized = r'\\.' + '\\' + normalized
            elif len(normalized) == 3 and normalized[1] == ':' and normalized[2] in ('\\', '/'):
                normalized = r'\\.' + '\\' + normalized[:2]
            drive_file, _ = DiskScanner._open_windows_drive(normalized)
            return drive_file
        return open(source_device, 'rb')

    def _carve_from_data_runs(
        self,
        scan_result: ScanResult,
        output_path: Path,
        source_device: str,
        data_runs: List[Dict],
        cluster_size: int,
        verify: bool,
    ) -> CarveResult:
        bytes_read = 0
        md5 = hashlib.md5()
        sha256 = hashlib.sha256()
        header_data = b""
        has_header = False

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with self._open_source_for_carving(source_device) as drive, open(output_path, 'wb') as out_f:
                for run in data_runs:
                    if self._stop_event.is_set():
                        raise Exception("Operação cancelada pelo usuário")
                    self._check_pause()

                    length_clusters = int(run.get('length_clusters') or 0)
                    if length_clusters <= 0:
                        continue

                    run_bytes = length_clusters * cluster_size
                    remaining = max(scan_result.size - bytes_read, 0)
                    if remaining <= 0:
                        break
                    bytes_to_consume = min(run_bytes, remaining)

                    lcn = run.get('lcn')
                    if lcn is None:
                        chunk = b'\x00' * bytes_to_consume
                        out_f.write(chunk)
                        md5.update(chunk)
                        sha256.update(chunk)
                        if not has_header:
                            header_data = chunk[:1024]
                            has_header = True
                        bytes_read += len(chunk)
                        continue

                    drive.seek(int(lcn) * cluster_size)
                    remaining_in_run = bytes_to_consume
                    while remaining_in_run > 0:
                        chunk = drive.read(min(CARVER_CHUNK_SIZE, remaining_in_run))
                        if not chunk:
                            break
                        out_f.write(chunk)
                        md5.update(chunk)
                        sha256.update(chunk)
                        if not has_header:
                            header_data = chunk[:1024]
                            has_header = True
                        bytes_read += len(chunk)
                        remaining_in_run -= len(chunk)

                if bytes_read == 0:
                    output_path.unlink(missing_ok=True)
                    raise IOError("Nenhum dado lido a partir dos data runs NTFS.")

            verification_status = 'unknown'
            if verify and has_header:
                if bytes_read <= 10 * 1024 * 1024:
                    with open(output_path, 'rb') as recovered:
                        verification_status = self._verify_file_integrity(recovered.read(), scan_result.extension)
                else:
                    verification_status = self._verify_generic(header_data, scan_result.extension)

            self.stats['files_processed'] += 1
            self.stats['files_success'] += 1
            self.stats['bytes_recovered'] += bytes_read
            return CarveResult(
                success=True,
                source_offset=scan_result.offset,
                recovered_path=str(output_path),
                original_size=scan_result.size,
                recovered_size=bytes_read,
                hash_md5=md5.hexdigest(),
                hash_sha256=sha256.hexdigest(),
                verification_status=verification_status,
            )
        except Exception as exc:
            logger.error("Erro ao recuperar arquivo via data runs NTFS: %s", exc)
            self.stats['files_processed'] += 1
            self.stats['files_failed'] += 1
            return CarveResult(
                success=False,
                source_offset=scan_result.offset,
                recovered_path=None,
                original_size=scan_result.size,
                recovered_size=0,
                hash_md5=None,
                hash_sha256=None,
                error_message=str(exc),
            )
    
    def carve_multiple(self,
                       drive_path: str,
                       scan_results: List[ScanResult],
                       progress_callback: Optional[Callable[[int, int, str], None]] = None,
                       verify: bool = True) -> List[CarveResult]:
        """
        Extrai múltiplos arquivos
        
        Args:
            drive_path: Caminho do drive
            scan_results: Lista de resultados da varredura
            progress_callback: Callback de progresso
            verify: Se deve verificar integridade
            
        Returns:
            Lista de CarveResult
        """
        results = []
        total = len(scan_results)
        
        self.stats['start_time'] = datetime.now()
        self._stop_event.clear()
        self._pause_event.set()
        
        for i, scan_result in enumerate(scan_results):
            if self._stop_event.is_set():
                break
            
            self._check_pause()
            
            # Gera nome único
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{i+1:04d}_{scan_result.file_type.replace(' ', '_')}_{timestamp}.{scan_result.extension}"
            
            # Cria subdiretório por tipo
            type_dir = self.output_dir / scan_result.extension
            type_dir.mkdir(exist_ok=True)
            
            output_path = type_dir / filename
            
            # Extrai arquivo
            result = self.carve_file(drive_path, scan_result, str(output_path), verify)
            results.append(result)
            
            # Callback de progresso
            if progress_callback:
                progress_callback(i + 1, total, f"Extraindo: {scan_result.file_type}")
        
        self.stats['elapsed_time'] = (datetime.now() - self.stats['start_time']).total_seconds()
        
        logger.info(f"Carving concluído: {self.stats['files_success']}/{total} arquivos recuperados")
        
        return results
    
    def _verify_file_integrity(self, data: bytes, extension: str) -> str:
        """
        Verifica integridade do arquivo recuperado
        
        Returns:
            'verified', 'partial', 'corrupted', ou 'unknown'
        """
        if len(data) == 0:
            return 'corrupted'
        
        # Verificações específicas por tipo
        verifiers = {
            'jpg': self._verify_jpg,
            'jpeg': self._verify_jpg,
            'png': self._verify_png,
            'gif': self._verify_gif,
            'pdf': self._verify_pdf,
            'zip': self._verify_zip,
            'mp4': self._verify_mp4,
            'mp3': self._verify_mp3,
            'wav': self._verify_wav,
            'docx': self._verify_office_openxml,
            'xlsx': self._verify_office_openxml,
            'pptx': self._verify_office_openxml,
        }
        
        verifier = verifiers.get(extension.lower())
        if verifier:
            return verifier(data)
        
        # Verificação genérica: verifica header e footer
        return self._verify_generic(data, extension)
    
    def _verify_jpg(self, data: bytes) -> str:
        """Verifica integridade de JPEG"""
        if len(data) < 10:
            return 'corrupted'
        
        # Verifica SOI e EOI markers
        has_soi = data[:2] == b'\xff\xd8'
        has_eoi = data[-2:] == b'\xff\xd9'
        
        if has_soi and has_eoi:
            # Verifica estrutura básica
            try:
                i = 2
                while i < len(data) - 2:
                    if data[i] == 0xFF:
                        marker = data[i + 1]
                        if marker == 0xD9:  # EOI
                            return 'verified'
                        elif marker in [0xD8, 0x00]:
                            i += 2
                        elif marker in [0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7]:
                            i += 2
                        elif marker in [0x01, 0xFE]:
                            i += 2
                        elif 0xD9 < marker <= 0xFE:
                            i += 2
                        else:
                            length = (data[i + 2] << 8) | data[i + 3]
                            i += 2 + length
                    else:
                        i += 1
                return 'partial' if has_soi else 'corrupted'
            except Exception:
                return 'partial' if has_soi else 'corrupted'
        elif has_soi:
            return 'partial'
        else:
            return 'corrupted'
    
    def _verify_png(self, data: bytes) -> str:
        """Verifica integridade de PNG"""
        if len(data) < 24:
            return 'corrupted'
        
        # Verifica assinatura
        valid_header = data[:8] == b'\x89PNG\r\n\x1a\n'
        # Verifica IEND
        valid_footer = data[-8:-4] == b'IEND' or b'IEND' in data[-20:]
        
        if valid_header and valid_footer:
            return 'verified'
        elif valid_header:
            return 'partial'
        else:
            return 'corrupted'
    
    def _verify_gif(self, data: bytes) -> str:
        """Verifica integridade de GIF"""
        if len(data) < 10:
            return 'corrupted'
        
        valid_header = data[:4] in [b'GIF87a', b'GIF89a']
        valid_footer = data[-1:] == b'\x3b' or b'\x00\x3b' in data[-10:]
        
        if valid_header and valid_footer:
            return 'verified'
        elif valid_header:
            return 'partial'
        else:
            return 'corrupted'
    
    def _verify_pdf(self, data: bytes) -> str:
        """Verifica integridade de PDF"""
        if len(data) < 10:
            return 'corrupted'
        
        valid_header = data[:4] == b'%PDF'
        valid_footer = b'%%EOF' in data[-20:]
        
        if valid_header and valid_footer:
            return 'verified'
        elif valid_header:
            return 'partial'
        else:
            return 'corrupted'
    
    def _verify_zip(self, data: bytes) -> str:
        """Verifica integridade de ZIP"""
        if len(data) < 22:
            return 'corrupted'
        
        valid_header = data[:4] == b'PK\x03\x04'
        valid_footer = data[-22:-18] == b'PK\x05\x06' or b'PK\x05\x06' in data[-100:]
        
        if valid_header and valid_footer:
            return 'verified'
        elif valid_header:
            return 'partial'
        else:
            return 'corrupted'
    
    def _verify_mp4(self, data: bytes) -> str:
        """Verifica integridade de MP4"""
        if len(data) < 16:
            return 'corrupted'
        
        # Verifica ftyp box
        has_ftyp = b'ftyp' in data[:100]
        
        if has_ftyp and len(data) > 1000:
            return 'verified'
        elif has_ftyp:
            return 'partial'
        else:
            return 'corrupted'
    
    def _verify_mp3(self, data: bytes) -> str:
        """Verifica integridade de MP3"""
        if len(data) < 10:
            return 'corrupted'
        
        # Verifica ID3 ou frame sync
        has_id3 = data[:3] == b'ID3'
        has_frame = data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
        
        if has_id3 or has_frame:
            return 'verified' if len(data) > 10000 else 'partial'
        else:
            return 'corrupted'
    
    def _verify_wav(self, data: bytes) -> str:
        """Verifica integridade de WAV"""
        if len(data) < 44:
            return 'corrupted'
        
        valid_header = data[:4] == b'RIFF' and data[8:12] == b'WAVE'
        
        if valid_header:
            return 'verified'
        else:
            return 'corrupted'
    
    def _verify_office_openxml(self, data: bytes) -> str:
        """Verifica integridade de documentos Office OpenXML"""
        if len(data) < 100:
            return 'corrupted'
        
        # Verifica assinatura ZIP
        valid_header = data[:4] == b'PK\x03\x04'
        # Verifica presença de [Content_Types].xml
        has_content_types = b'[Content_Types].xml' in data[:5000]
        
        if valid_header and has_content_types:
            return 'verified'
        elif valid_header:
            return 'partial'
        else:
            return 'corrupted'
    
    def _verify_generic(self, data: bytes, extension: str) -> str:
        """Verificação genérica de arquivo"""
        if len(data) == 0:
            return 'corrupted'
        
        # Verifica se tem conteúdo significativo
        if len(data) < 100:
            return 'partial'
        
        # Verifica se não é apenas zeros ou dados aleatórios
        zero_count = data.count(b'\x00')
        if zero_count > len(data) * 0.9:
            return 'corrupted'
        
        return 'verified'
    
    def get_stats(self) -> Dict:
        """Retorna estatísticas do carving"""
        stats = self.stats.copy()
        if self.stats['start_time']:
            stats['elapsed_time'] = (datetime.now() - self.stats['start_time']).total_seconds()
        return stats
    
    def generate_report(self, results: List[CarveResult], output_file: Optional[str] = None) -> str:
        """Gera relatório de recuperação"""
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = self.output_dir / f"recovery_report_{timestamp}.txt"
        
        lines = [
            "=" * 70,
            "REVIVAX - RELATÓRIO DE RECUPERAÇÃO",
            "=" * 70,
            f"Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total de arquivos processados: {len(results)}",
            f"Arquivos recuperados com sucesso: {sum(1 for r in results if r.success)}",
            f"Arquivos com falha: {sum(1 for r in results if not r.success)}",
            "-" * 70,
            "",
            "DETALHES:",
            "-" * 70,
        ]
        
        for i, result in enumerate(results, 1):
            status = "✓ SUCESSO" if result.success else "✗ FALHA"
            lines.append(f"\n[{i}] {status}")
            lines.append(f"    Offset: {result.source_offset}")
            lines.append(f"    Tamanho original: {result.original_size} bytes")
            
            if result.success:
                lines.append(f"    Tamanho recuperado: {result.recovered_size} bytes")
                lines.append(f"    Caminho: {result.recovered_path}")
                lines.append(f"    MD5: {result.hash_md5}")
                lines.append(f"    SHA256: {result.hash_sha256}")
                lines.append(f"    Verificação: {result.verification_status}")
            else:
                lines.append(f"    Erro: {result.error_message}")
        
        lines.extend([
            "",
            "=" * 70,
            "FIM DO RELATÓRIO",
            "=" * 70,
        ])
        
        report_text = "\n".join(lines)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_text)
        
        logger.info(f"Relatório gerado: {output_file}")
        
        return report_text


if __name__ == '__main__':
    # Teste do carver
    logging.basicConfig(level=logging.INFO)
    
    carver = FileCarver()
    print(f"Diretório de saída: {carver.output_dir}")
