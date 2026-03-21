"""
RevivaX - Recovery Module
Módulo de recuperação de arquivos com gerenciamento completo

Variáveis de ambiente suportadas:
- ``REVIVAX_RESTORE_LAST_JOB``: quando definida como ``1``, ``true``,
  ``yes`` ou ``on``, habilita a restauração automática do último job salvo.
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import threading

from .scanner import DiskScanner, ScanResult, ScanMode, get_available_drives, get_scan_target_context
from .carver import FileCarver, CarveResult
from .runtime_paths import get_runtime_root

logger = logging.getLogger(__name__)
PROJECT_ROOT = get_runtime_root()


class RecoveryStatus(Enum):
    """Status da operação de recuperação"""
    IDLE = "idle"
    SCANNING = "scanning"
    PAUSED = "paused"
    CARVING = "carving"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class RecoveryJob:
    """Representa um job de recuperação"""
    id: str
    drive_path: str
    mode: ScanMode
    file_types: Optional[List[str]]
    status: RecoveryStatus
    created_at: datetime
    updated_at: datetime
    scan_results: List[ScanResult] = None
    carve_results: List[CarveResult] = None
    stats: Dict = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.scan_results is None:
            self.scan_results = []
        if self.carve_results is None:
            self.carve_results = []
        if self.stats is None:
            self.stats = {}


class RecoveryManager:
    """
    Gerenciador completo de recuperação de arquivos
    Coordena scanner e carver com interface unificada
    """
    
    def __init__(self, output_dir: str = "recovered", logs_dir: str = "logs"):
        self.output_dir = self._resolve_storage_path(output_dir)
        self.logs_dir = self._resolve_storage_path(logs_dir)
        
        # Cria diretórios
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Componentes
        self.scanner = DiskScanner(read_only=True)
        self.carver = FileCarver(output_dir=str(self.output_dir), read_only=True)
        
        # Estado
        self.current_job: Optional[RecoveryJob] = None
        self.jobs_history: List[RecoveryJob] = []
        self._lock = threading.Lock()
        
        # Callbacks
        self._progress_callback: Optional[Callable] = None
        self._status_callback: Optional[Callable] = None
        
        # Configuração de logging
        self._setup_logging()
        
        # Restauração persistida é opt-in para não contaminar sessões novas.
        if self._should_restore_last_job():
            self.load_state()

    @staticmethod
    def _resolve_storage_path(path_value: str) -> Path:
        """Resolve caminhos relativos a partir da raiz do projeto."""
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @staticmethod
    def _should_restore_last_job() -> bool:
        """
        Verifica se a restauração automática do último job está habilitada.

        O comportamento é opt-in e controlado por ``REVIVAX_RESTORE_LAST_JOB``.
        Apenas valores afirmativos explícitos ativam a restauração.
        """
        value = os.environ.get('REVIVAX_RESTORE_LAST_JOB', '').strip().lower()
        return value in {'1', 'true', 'yes', 'on'}
    
    def _setup_logging(self):
        """Configura logging para arquivo"""
        log_file = self.logs_dir / f"revivax_{datetime.now().strftime('%Y%m%d')}.log"
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
    
    def set_callbacks(self,
                     progress_callback: Optional[Callable[[int, int, str], None]] = None,
                     status_callback: Optional[Callable[[RecoveryStatus, str], None]] = None):
        """Define callbacks para atualizações"""
        self._progress_callback = progress_callback
        self._status_callback = status_callback
    
    def _update_status(self, status: RecoveryStatus, message: str = ""):
        """Atualiza status e chama callback"""
        if self.current_job:
            self.current_job.status = status
            self.current_job.updated_at = datetime.now()
        
        if self._status_callback:
            self._status_callback(status, message)
        
        logger.info(f"Status: {status.value} - {message}")
    
    def _progress_wrapper(self, current: int, total: int, message: str):
        """Wrapper para callback de progresso"""
        if self._progress_callback:
            self._progress_callback(current, total, message)

    @staticmethod
    def get_scan_source_kind(drive_path: str) -> str:
        """Classifica o alvo como drive raw ou pasta acessível."""
        return get_scan_target_context(drive_path).get('source_kind', 'drive')

    @classmethod
    def get_effective_scan_mode(cls, drive_path: str, mode: ScanMode) -> ScanMode:
        """
        Normaliza o modo de varredura para o que o backend realmente executa.

        Em modo pasta, a profundidade depende do filesystem suportado.
        """
        context = get_scan_target_context(drive_path, mode)
        effective = context.get('effective_mode') or mode.value
        return ScanMode.QUICK if effective == ScanMode.QUICK.value else ScanMode.DEEP

    @staticmethod
    def get_scan_target_context(drive_path: str, mode: Optional[ScanMode] = None) -> Dict:
        return get_scan_target_context(drive_path, mode or ScanMode.QUICK)
    
    def create_job(self,
                   drive_path: str,
                   mode: ScanMode = ScanMode.QUICK,
                   file_types: Optional[List[str]] = None,
                   job_id: Optional[str] = None) -> RecoveryJob:
        """
        Cria um novo job de recuperação
        
        Args:
            drive_path: Caminho do drive a ser escaneado
            mode: Modo de varredura (QUICK ou DEEP)
            file_types: Lista de extensões para filtrar
            
        Returns:
            RecoveryJob criado
        """
        job_id = job_id or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        
        effective_mode = self.get_effective_scan_mode(drive_path, mode)
        job = RecoveryJob(
            id=job_id,
            drive_path=drive_path,
            mode=effective_mode,
            file_types=file_types,
            status=RecoveryStatus.IDLE,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        with self._lock:
            self.current_job = job
        
        logger.info(
            "Job criado: %s - Drive: %s - Requested mode: %s - Effective mode: %s",
            job_id,
            drive_path,
            mode.value,
            effective_mode.value,
        )
        
        return job
    
    def start_recovery(self, 
                       drive_path: str,
                       mode: ScanMode = ScanMode.QUICK,
                       file_types: Optional[List[str]] = None,
                       auto_carve: bool = True) -> RecoveryJob:
        """
        Inicia processo completo de recuperação
        
        Args:
            drive_path: Caminho do drive
            mode: Modo de varredura
            file_types: Tipos de arquivo para filtrar
            auto_carve: Se deve extrair arquivos automaticamente
            
        Returns:
            RecoveryJob com resultados
        """
        # Cria job
        job = self.create_job(drive_path, mode, file_types)
        
        try:
            # Fase 1: Varredura
            self._update_status(RecoveryStatus.SCANNING, "Iniciando varredura...")
            
            scan_results = self.scanner.scan_drive(
                drive_path=drive_path,
                mode=job.mode,
                file_types=file_types,
                progress_callback=self._progress_wrapper
            )
            scan_context = self.scanner.get_last_scan_context()
            job.mode = ScanMode.DEEP if scan_context.get('effective_mode') == ScanMode.DEEP.value else ScanMode.QUICK
            
            job.scan_results = scan_results
            job.stats['scan'] = self.scanner.get_stats()
            job.stats['scan_context'] = scan_context
            
            logger.info(f"Varredura concluída: {len(scan_results)} arquivos encontrados")
            
            # Fase 2: Carving (se solicitado e houver resultados)
            if auto_carve and scan_results:
                self._update_status(RecoveryStatus.CARVING, "Extraindo arquivos...")
                
                # Filtra apenas arquivos com boa confiança
                good_results = [r for r in scan_results if r.confidence >= 0.5]
                
                if good_results:
                    carve_results = self.carver.carve_multiple(
                        drive_path=drive_path,
                        scan_results=good_results,
                        progress_callback=self._progress_wrapper,
                        verify=True
                    )
                    
                    job.carve_results = carve_results
                    job.stats['carve'] = self.carver.get_stats()
                    
                    logger.info(f"Carving concluído: {len([r for r in carve_results if r.success])} arquivos recuperados")
            
            # Finaliza
            self._update_status(RecoveryStatus.COMPLETED, "Recuperação concluída com sucesso")
            
            # Salva relatório
            self._save_job_report(job)
            
        except Exception as e:
            logger.error(f"Erro durante recuperação: {e}")
            job.status = RecoveryStatus.ERROR
            job.error_message = str(e)
            self._update_status(RecoveryStatus.ERROR, str(e))
            raise
        
        finally:
            with self._lock:
                self.jobs_history.append(job)
        
        return job
    
    def start_scan_only(self,
                       drive_path: str,
                       mode: ScanMode = ScanMode.QUICK,
                       file_types: Optional[List[str]] = None,
                       job_id: Optional[str] = None) -> RecoveryJob:
        """
        Executa apenas a varredura sem extrair arquivos
        
        Args:
            drive_path: Caminho do drive
            mode: Modo de varredura
            file_types: Tipos de arquivo para filtrar
            
        Returns:
            RecoveryJob com resultados da varredura
        """
        job = self.create_job(drive_path, mode, file_types, job_id=job_id)
        
        try:
            self._update_status(RecoveryStatus.SCANNING, "Iniciando varredura...")
            
            scan_results = self.scanner.scan_drive(
                drive_path=drive_path,
                mode=job.mode,
                file_types=file_types,
                progress_callback=self._progress_wrapper
            )
            scan_context = self.scanner.get_last_scan_context()
            job.mode = ScanMode.DEEP if scan_context.get('effective_mode') == ScanMode.DEEP.value else ScanMode.QUICK
            
            job.scan_results = scan_results
            job.stats['scan'] = self.scanner.get_stats()
            job.stats['scan_context'] = scan_context
            
            self._update_status(RecoveryStatus.COMPLETED, f"Varredura concluída: {len(scan_results)} arquivos encontrados")
            
            self._save_job_report(job)
            
        except Exception as e:
            logger.error(f"Erro durante varredura: {e}")
            job.status = RecoveryStatus.ERROR
            job.error_message = str(e)
            self._update_status(RecoveryStatus.ERROR, str(e))
            raise
        
        finally:
            with self._lock:
                self.jobs_history.append(job)
        
        return job
    
    def carve_selected(self,
                      drive_path: str,
                      scan_results: List[ScanResult]) -> List[CarveResult]:
        """
        Extrai arquivos selecionados
        
        Args:
            drive_path: Caminho do drive
            scan_results: Lista de resultados para extrair
            
        Returns:
            Lista de CarveResult
        """
        self._update_status(RecoveryStatus.CARVING, "Extraindo arquivos selecionados...")
        
        results = self.carver.carve_multiple(
            drive_path=drive_path,
            scan_results=scan_results,
            progress_callback=self._progress_wrapper,
            verify=True
        )
        
        # Gera relatório
        self.carver.generate_report(results)
        
        self._update_status(RecoveryStatus.COMPLETED, f"Extração concluída: {len([r for r in results if r.success])} arquivos recuperados")
        
        return results
    
    def pause(self):
        """Pausa operação atual"""
        self.scanner.pause()
        self.carver.pause()
        self._update_status(RecoveryStatus.PAUSED, "Operação pausada")
    
    def resume(self):
        """Retoma operação pausada"""
        self.scanner.resume()
        self.carver.resume()
        self._update_status(RecoveryStatus.SCANNING, "Operação retomada")
    
    def stop(self):
        """Para operação atual"""
        self.scanner.stop()
        self.carver.stop()
        self._update_status(RecoveryStatus.CANCELLED, "Operação cancelada")
    
    def get_current_job(self) -> Optional[RecoveryJob]:
        """Retorna job atual"""
        with self._lock:
            return self.current_job
    
    def get_jobs_history(self) -> List[RecoveryJob]:
        """Retorna histórico de jobs"""
        with self._lock:
            return self.jobs_history.copy()
    
    def get_drives(self) -> List[Dict]:
        """Retorna lista de drives disponíveis"""
        return get_available_drives()
    
    def get_supported_file_types(self) -> List[Dict]:
        """Retorna lista de tipos de arquivo suportados"""
        from .scanner import FILE_SIGNATURES
        
        types = {}
        for sig in FILE_SIGNATURES:
            if sig.extension not in types:
                types[sig.extension] = {
                    'extension': sig.extension,
                    'name': sig.name,
                    'mime_type': sig.mime_type,
                    'category': self._get_category(sig.extension)
                }
        
        return list(types.values())
    
    def _get_category(self, extension: str) -> str:
        """Retorna categoria do tipo de arquivo"""
        categories = {
            'jpg': 'image', 'jpeg': 'image', 'png': 'image', 'gif': 'image',
            'bmp': 'image', 'tiff': 'image', 'webp': 'image', 'avif': 'image',
            'svg': 'image', 'ico': 'image', 'psd': 'image', 'eps': 'image',
            'mp4': 'video', 'avi': 'video', 'mkv': 'video', 'mov': 'video',
            'wmv': 'video', 'flv': 'video',
            'mp3': 'audio', 'wav': 'audio', 'flac': 'audio', 'ogg': 'audio',
            'aac': 'audio', 'm4a': 'audio',
            'pdf': 'document', 'doc': 'document', 'docx': 'document',
            'xls': 'document', 'xlsx': 'document', 'ppt': 'document',
            'pptx': 'document', 'odt': 'document', 'rtf': 'document',
            'txt': 'document',
            'zip': 'archive', 'rar': 'archive', '7z': 'archive',
            'gz': 'archive', 'bz2': 'archive', 'tar': 'archive',
            'exe': 'executable', 'dll': 'executable', 'elf': 'executable',
            'sqlite': 'database', 'mdb': 'database',
            'iso': 'disk', 'ps': 'document',
            'ttf': 'font', 'otf': 'font'
        }
        return categories.get(extension.lower(), 'other')
    
    def _save_job_report(self, job: RecoveryJob):
        """Salva relatório do job em JSON"""
        report_file = self.logs_dir / f"job_{job.id}.json"
        
        report_data = {
            'id': job.id,
            'drive_path': job.drive_path,
            'mode': job.mode.value,
            'file_types': job.file_types,
            'status': job.status.value,
            'created_at': job.created_at.isoformat(),
            'updated_at': job.updated_at.isoformat(),
            'stats': job.stats,
            'error_message': job.error_message,
            'scan_results_count': len(job.scan_results),
            'carve_results_count': len(job.carve_results),
            'scan_results': [
                {
                    'offset': r.offset,
                    'size': r.size,
                    'file_type': r.file_type,
                    'extension': r.extension,
                    'confidence': r.confidence,
                    'signature_matched': r.signature_matched,
                    'is_fragmented': r.is_fragmented,
                    'metadata': r.metadata,
                }
                for r in job.scan_results
            ],
            'carve_results': [
                {
                    'success': r.success,
                    'source_offset': r.source_offset,
                    'recovered_path': r.recovered_path,
                    'original_size': r.original_size,
                    'recovered_size': r.recovered_size,
                    'hash_md5': r.hash_md5,
                    'hash_sha256': r.hash_sha256,
                    'verification_status': r.verification_status,
                    'error_message': r.error_message
                }
                for r in job.carve_results
            ] if job.carve_results else []
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Relatório salvo: {report_file}")
        self.save_state()
        
    def save_state(self):
        """Salva o ID do job atual para restaurar na próxima execução (ARCH-02)."""
        if self.current_job:
            state_file = self.logs_dir / ".last_job"
            try:
                with open(state_file, 'w', encoding='utf-8') as f:
                    f.write(self.current_job.id)
            except Exception as e:
                logger.error(f"Erro ao gravar id do cache assíncrono: {e}")

    def clear_saved_state(self):
        """Remove o ponteiro persistido para o último job."""
        state_file = self.logs_dir / ".last_job"
        try:
            if state_file.exists():
                state_file.unlink()
        except Exception as e:
            logger.error(f"Erro ao limpar cache do último job: {e}")

    def reset_current_job(self, clear_persisted_state: bool = False):
        """Limpa o job atual em memória e, opcionalmente, o ponteiro persistido."""
        with self._lock:
            self.current_job = None
        if clear_persisted_state:
            self.clear_saved_state()

    def load_state(self):
        """Restaura o job anterior e preenche a sessão se houver (ARCH-02)."""
        state_file = self.logs_dir / ".last_job"
        if not state_file.exists():
            return
            
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                last_job_id = f.read().strip()
                
            data = self.load_job_report(last_job_id)
            if not data:
                return

            scans = [ScanResult(**s) for s in data.get('scan_results', [])]
            carves = [CarveResult(**c) for c in data.get('carve_results', [])]
            
            mode_val = data.get('mode')
            mode = ScanMode.QUICK if mode_val == 'quick' else ScanMode.DEEP
            status_val = data.get('status')
            try:
                status = RecoveryStatus(status_val)
            except ValueError:
                status = RecoveryStatus.ERROR

            job = RecoveryJob(
                id=data['id'],
                drive_path=data['drive_path'],
                mode=mode,
                file_types=data['file_types'],
                status=status,
                created_at=datetime.fromisoformat(data['created_at']),
                updated_at=datetime.fromisoformat(data['updated_at']),
                scan_results=scans,
                carve_results=carves,
                stats=data.get('stats', {}),
                error_message=data.get('error_message')
            )
            
            with self._lock:
                self.current_job = job
                
            logger.info(f"Estado restaurado (ARCH-02 Cache) do Job {last_job_id} com {len(scans)} arquivos.")
        except Exception as e:
            logger.error(f"Falha ao restaurar cache do Job anterior: {e}")
            
    def load_job_report(self, job_id: str) -> Optional[Dict]:
        """Carrega relatório de um job"""
        report_file = self.logs_dir / f"job_{job_id}.json"
        
        if report_file.exists():
            with open(report_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        return None
    
    def get_recovery_estimate(self, drive_path: str) -> Dict:
        """
        Estima chance de recuperação para um drive
        
        Returns:
            Dict com estimativas
        """
        try:
            import psutil
            
            # Tenta obter informações do drive
            for partition in psutil.disk_partitions():
                if partition.device == drive_path or partition.mountpoint == drive_path:
                    usage = psutil.disk_usage(partition.mountpoint)
                    
                    # Estimativa baseada em espaço livre
                    free_percent = (usage.free / usage.total) * 100
                    
                    # Quanto mais espaço livre, maior chance de recuperação
                    # (dados antigos menos prováveis de serem sobrescritos)
                    if free_percent > 50:
                        chance = "high"
                        description = "Excelentes chances de recuperação. Muito espaço livre disponível."
                    elif free_percent > 20:
                        chance = "medium"
                        description = "Boas chances de recuperação. Alguns dados podem estar sobrescritos."
                    else:
                        chance = "low"
                        description = "Chances limitadas. Muitos dados podem estar sobrescritos."
                    
                    return {
                        'drive': drive_path,
                        'total_space': usage.total,
                        'used_space': usage.used,
                        'free_space': usage.free,
                        'free_percent': free_percent,
                        'recovery_chance': chance,
                        'description': description,
                        'recommendation': 'Use varredura profunda para melhores resultados' if chance == 'low' else 'Varredura rápida deve ser suficiente'
                    }
            
            return {
                'drive': drive_path,
                'error': 'Drive não encontrado',
                'recovery_chance': 'unknown',
                'description': 'Não foi possível obter informações do drive'
            }
            
        except Exception as e:
            logger.error(f"Erro ao estimar recuperação: {e}")
            return {
                'drive': drive_path,
                'error': str(e),
                'recovery_chance': 'unknown',
                'description': 'Erro ao analisar drive'
            }


# Instância global do manager
_recovery_manager: Optional[RecoveryManager] = None


def get_recovery_manager() -> RecoveryManager:
    """Retorna instância global do RecoveryManager"""
    global _recovery_manager
    if _recovery_manager is None:
        _recovery_manager = RecoveryManager()
    return _recovery_manager


if __name__ == '__main__':
    # Teste do recovery manager
    logging.basicConfig(level=logging.INFO)
    
    manager = RecoveryManager()
    
    print("Tipos de arquivo suportados:")
    for ft in manager.get_supported_file_types()[:10]:
        print(f"  .{ft['extension']}: {ft['name']} ({ft['category']})")
    
    print(f"\nTotal: {len(manager.get_supported_file_types())} tipos")
