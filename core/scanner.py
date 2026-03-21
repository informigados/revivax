"""
RevivaX - Scanner Module
Módulo de varredura de disco para recuperação de arquivos
"""

import os
import re
import struct
import logging
import mmap
import base64
from contextlib import contextmanager
from pathlib import Path
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading
import time

from .ntfs import (
    build_full_paths,
    collect_descendants,
    iter_mft_records,
    open_binary_stream,
    read_boot_sector,
    resolve_folder_record,
)

logger = logging.getLogger(__name__)

WINDOWS_DRIVE_RE = re.compile(r'[A-Za-z]:\\?')
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r'[A-Za-z]:(?:\\.*)?')
WINDOWS_RAW_DEVICE_RE = re.compile(r'\\\\\.\\PHYSICALDRIVE\d+', re.IGNORECASE)

EXTENSION_CATEGORY_MAP = {
    'jpg': 'image', 'jpeg': 'image', 'png': 'image', 'gif': 'image', 'bmp': 'image',
    'tiff': 'image', 'webp': 'image', 'avif': 'image', 'psd': 'image', 'svg': 'image',
    'ico': 'image',
    'mp4': 'video', 'avi': 'video', 'mkv': 'video', 'mov': 'video', 'wmv': 'video',
    'flv': 'video',
    'mp3': 'audio', 'wav': 'audio', 'flac': 'audio', 'ogg': 'audio', 'aac': 'audio',
    'm4a': 'audio',
    'pdf': 'document', 'doc': 'document', 'docx': 'document', 'xls': 'document',
    'xlsx': 'document', 'ppt': 'document', 'pptx': 'document', 'txt': 'document',
    'rtf': 'document',
    'zip': 'archive', 'rar': 'archive', '7z': 'archive', 'gz': 'archive',
    'bz2': 'archive', 'tar': 'archive',
}


def get_extension_category(extension: str) -> str:
    """Retorna a categoria funcional de uma extensão."""
    return EXTENSION_CATEGORY_MAP.get((extension or '').lower(), 'other')


def _normalize_path_for_match(path: str) -> str:
    expanded = os.path.abspath(os.path.expanduser(path or ""))
    if os.name == 'nt':
        normalized = expanded.replace('/', '\\').rstrip('\\')
        if len(normalized) == 2 and normalized[1] == ':':
            normalized += '\\'
        return normalized.upper()
    return expanded.rstrip('/') or '/'


def _sanitize_scan_target_path(target_path: str) -> str:
    candidate = (target_path or '').strip()
    if not candidate:
        raise ValueError("scan target is required")

    if os.name == 'nt':
        normalized = candidate.replace('/', '\\')
        if WINDOWS_RAW_DEVICE_RE.fullmatch(normalized):
            return normalized.upper()
        if WINDOWS_DRIVE_RE.fullmatch(normalized):
            return normalized[:2].upper()
        if not WINDOWS_ABSOLUTE_PATH_RE.fullmatch(normalized):
            raise ValueError("scan target must be an absolute local path")
        candidate = normalized
    elif not candidate.startswith('/'):
        raise ValueError("scan target must be an absolute path")

    path_obj = Path(candidate).expanduser()
    if not path_obj.is_absolute():
        raise ValueError("scan target must be absolute")
    resolved = path_obj.resolve(strict=False)
    if os.name == 'nt' and str(resolved).startswith('\\\\'):
        raise ValueError("UNC scan targets are not supported")
    return str(resolved)


def _get_partition_for_path(target_path: str) -> Optional[Dict]:
    try:
        import psutil
    except ImportError:
        return None

    normalized_target = _normalize_path_for_match(target_path)
    partitions = sorted(
        psutil.disk_partitions(),
        key=lambda part: len(_normalize_path_for_match(part.mountpoint)),
        reverse=True,
    )

    for partition in partitions:
        mount = _normalize_path_for_match(partition.mountpoint)
        if os.name == 'nt':
            if normalized_target.startswith(mount):
                return {
                    'device': partition.device.rstrip('\\'),
                    'mountpoint': partition.mountpoint,
                    'fstype': (partition.fstype or '').upper(),
                    'opts': partition.opts,
                }
        else:
            if normalized_target == mount or normalized_target.startswith(f"{mount}/"):
                return {
                    'device': partition.device,
                    'mountpoint': partition.mountpoint,
                    'fstype': (partition.fstype or '').upper(),
                    'opts': partition.opts,
                }
    return None


def get_scan_target_context(target_path: str, requested_mode: Optional["ScanMode"] = None) -> Dict[str, Optional[str]]:
    sanitized_target = _sanitize_scan_target_path(target_path)
    requested = requested_mode.value if isinstance(requested_mode, ScanMode) else str(requested_mode or ScanMode.QUICK.value)
    is_directory_target = (
        not (os.name == 'nt' and WINDOWS_RAW_DEVICE_RE.fullmatch(sanitized_target))
        and os.path.isdir(sanitized_target)
    )
    if is_directory_target:
        partition = _get_partition_for_path(sanitized_target) or {}
        filesystem = (partition.get('fstype') or '').upper() or 'UNKNOWN'
        supports_deep_folder_scan = os.name == 'nt' and filesystem == 'NTFS' and bool(partition.get('device'))
        effective_mode = requested
        strategy = 'filesystem_walk'
        note_code = 'folder_accessible_files'
        if requested == ScanMode.DEEP.value:
            if supports_deep_folder_scan:
                strategy = 'ntfs_mft'
                note_code = 'folder_ntfs_metadata'
            else:
                effective_mode = ScanMode.QUICK.value
                note_code = 'folder_deep_unsupported'
        return {
            'source_kind': 'folder',
            'filesystem': filesystem,
            'volume_device': partition.get('device'),
            'volume_mountpoint': partition.get('mountpoint'),
            'supports_deep_folder_scan': supports_deep_folder_scan,
            'requested_mode': requested,
            'effective_mode': effective_mode,
            'strategy': strategy,
            'note_code': note_code,
        }

    return {
        'source_kind': 'drive',
        'filesystem': None,
        'volume_device': sanitized_target,
        'volume_mountpoint': sanitized_target,
        'supports_deep_folder_scan': False,
        'requested_mode': requested,
        'effective_mode': requested,
        'strategy': 'raw_signature_scan',
        'note_code': 'drive_raw_signature',
    }


class ScanMode(Enum):
    """Modos de varredura disponíveis"""
    QUICK = "quick"
    DEEP = "deep"


@dataclass
class ScanResult:
    """Resultado de um arquivo encontrado na varredura"""
    offset: int
    size: int
    file_type: str
    extension: str
    confidence: float  # 0.0 a 1.0
    signature_matched: str
    is_fragmented: bool = False
    metadata: Dict = field(default_factory=dict)


@dataclass
class FileSignature:
    """Assinatura de arquivo para identificação"""
    name: str
    extension: str
    mime_type: str
    signatures: List[bytes]  # Múltiplas assinaturas possíveis
    footers: List[bytes] = field(default_factory=list)
    max_size: int = 100 * 1024 * 1024  # 100MB padrão
    min_size: int = 0


# Assinaturas de arquivos suportados
FILE_SIGNATURES = [
    # ── Imagens ────────────────────────────────────────────────
    FileSignature(
        name="JPEG Image", extension="jpg", mime_type="image/jpeg",
        signatures=[b'\xff\xd8\xff\xe0', b'\xff\xd8\xff\xe1',
                    b'\xff\xd8\xff\xe8', b'\xff\xd8\xff\xdb'],
        footers=[b'\xff\xd9'],
        min_size=4 * 1024,          # mínimo 4 KB
        max_size=50 * 1024 * 1024
    ),
    FileSignature(
        name="PNG Image", extension="png", mime_type="image/png",
        signatures=[b'\x89PNG\r\n\x1a\n'],
        footers=[b'IEND\xaeB`\x82'],
        min_size=1 * 1024,
        max_size=30 * 1024 * 1024
    ),
    FileSignature(
        name="GIF Image", extension="gif", mime_type="image/gif",
        signatures=[b'GIF87a', b'GIF89a'],
        footers=[b'\x00\x3b'],
        min_size=512,
        max_size=10 * 1024 * 1024
    ),
    FileSignature(
        name="BMP Image", extension="bmp", mime_type="image/bmp",
        signatures=[b'BM'],
        min_size=54,                # BMP header mínimo
        max_size=20 * 1024 * 1024
    ),
    FileSignature(
        name="TIFF Image", extension="tiff", mime_type="image/tiff",
        signatures=[b'II*\x00', b'MM\x00*'],
        min_size=1 * 1024,
        max_size=50 * 1024 * 1024
    ),
    FileSignature(
        name="WebP Image", extension="webp", mime_type="image/webp",
        signatures=[b'RIFF\x00\x00\x00\x00WEBP', b'WEBP'],  # mais específico
        min_size=1 * 1024,
        max_size=20 * 1024 * 1024
    ),
    FileSignature(
        name="AVIF Image", extension="avif", mime_type="image/avif",
        signatures=[b'\x00\x00\x00\x20ftypavif'],
        min_size=1 * 1024,
        max_size=20 * 1024 * 1024
    ),
    FileSignature(
        name="ICO Icon", extension="ico", mime_type="image/x-icon",
        signatures=[b'\x00\x00\x01\x00'],
        min_size=40,
        max_size=5 * 1024 * 1024
    ),

    # ── Vídeos ─────────────────────────────────────────────────
    FileSignature(
        name="MP4 Video", extension="mp4", mime_type="video/mp4",
        signatures=[b'ftypmp4', b'ftypisom', b'ftypM4V ', b'ftyp'],
        min_size=1 * 1024 * 1024,   # vídeos têm > 1 MB
        max_size=2 * 1024 * 1024 * 1024
    ),
    FileSignature(
        name="AVI Video", extension="avi", mime_type="video/x-msvideo",
        signatures=[b'RIFF\x00\x00\x00\x00AVI '],  # mais específico que 'RIFF'
        min_size=1 * 1024 * 1024,
        max_size=2 * 1024 * 1024 * 1024
    ),
    FileSignature(
        name="MKV Video", extension="mkv", mime_type="video/x-matroska",
        signatures=[b'\x1aE\xdf\xa3'],
        min_size=1 * 1024 * 1024,
        max_size=4 * 1024 * 1024 * 1024
    ),
    FileSignature(
        name="MOV Video", extension="mov", mime_type="video/quicktime",
        signatures=[b'ftypqt  ', b'moov'],
        min_size=1 * 1024 * 1024,
        max_size=2 * 1024 * 1024 * 1024
    ),
    FileSignature(
        name="WMV Video", extension="wmv", mime_type="video/x-ms-wmv",
        signatures=[b'\x30\x26\xb2\x75\x8e\x66\xcf\x11'],
        min_size=512 * 1024,
        max_size=2 * 1024 * 1024 * 1024
    ),
    FileSignature(
        name="FLV Video", extension="flv", mime_type="video/x-flv",
        signatures=[b'FLV\x01'],
        min_size=512 * 1024,
        max_size=1 * 1024 * 1024 * 1024
    ),

    # ── Documentos ─────────────────────────────────────────────
    FileSignature(
        name="PDF Document", extension="pdf", mime_type="application/pdf",
        signatures=[b'%PDF-1.'],
        footers=[b'%%EOF'],
        min_size=4 * 1024,
        max_size=100 * 1024 * 1024
    ),
    FileSignature(
        name="Microsoft Word", extension="doc", mime_type="application/msword",
        signatures=[b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'],
        min_size=8 * 1024,
        max_size=50 * 1024 * 1024
    ),
    FileSignature(
        name="Microsoft Word (OpenXML)", extension="docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        signatures=[b'PK\x03\x04'],  # ZIP header — usado por docx/xlsx/pptx
        min_size=8 * 1024,
        max_size=50 * 1024 * 1024
    ),
    FileSignature(
        name="Microsoft Excel (OpenXML)", extension="xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        signatures=[b'PK\x03\x04\x14\x00\x06\x00'],  # ZIP local file header específico
        min_size=8 * 1024,
        max_size=50 * 1024 * 1024
    ),
    FileSignature(
        name="Microsoft PowerPoint (OpenXML)", extension="pptx",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        signatures=[b'PK\x03\x04\x14\x00\x00\x00'],
        min_size=16 * 1024,
        max_size=100 * 1024 * 1024
    ),
    FileSignature(
        name="Rich Text Format", extension="rtf", mime_type="application/rtf",
        signatures=[b'{\\rtf1'],
        min_size=1 * 1024,
        max_size=20 * 1024 * 1024
    ),

    # ── Áudio ──────────────────────────────────────────────────
    FileSignature(
        name="MP3 Audio", extension="mp3", mime_type="audio/mpeg",
        signatures=[b'ID3'],        # somente ID3 tag — \xff\xfb muito frequente
        min_size=64 * 1024,
        max_size=500 * 1024 * 1024
    ),
    FileSignature(
        name="WAV Audio", extension="wav", mime_type="audio/wav",
        signatures=[b'RIFF\x00\x00\x00\x00WAVE'],  # mais específico
        min_size=44,
        max_size=500 * 1024 * 1024
    ),
    FileSignature(
        name="FLAC Audio", extension="flac", mime_type="audio/flac",
        signatures=[b'fLaC'],
        min_size=64 * 1024,
        max_size=500 * 1024 * 1024
    ),
    FileSignature(
        name="OGG Audio", extension="ogg", mime_type="audio/ogg",
        signatures=[b'OggS'],
        min_size=64 * 1024,
        max_size=500 * 1024 * 1024
    ),
    FileSignature(
        name="AAC Audio", extension="aac", mime_type="audio/aac",
        signatures=[b'\xff\xf1', b'\xff\xf9'],
        min_size=64 * 1024,
        max_size=200 * 1024 * 1024
    ),

    # ── Arquivos Compactados ────────────────────────────────────
    FileSignature(
        name="ZIP Archive", extension="zip", mime_type="application/zip",
        signatures=[b'PK\x03\x04'],
        footers=[b'PK\x05\x06'],
        min_size=1 * 1024,
        max_size=2 * 1024 * 1024 * 1024
    ),
    FileSignature(
        name="RAR Archive", extension="rar", mime_type="application/x-rar",
        signatures=[b'Rar!\x1a\x07\x00', b'Rar!\x1a\x07\x01\x00'],
        min_size=1 * 1024,
        max_size=2 * 1024 * 1024 * 1024
    ),
    FileSignature(
        name="7-Zip Archive", extension="7z", mime_type="application/x-7z-compressed",
        signatures=[b"7z\xbc\xaf'\x1c"],
        min_size=1 * 1024,
        max_size=2 * 1024 * 1024 * 1024
    ),
    FileSignature(
        name="GZIP Archive", extension="gz", mime_type="application/gzip",
        signatures=[b'\x1f\x8b\x08'],
        min_size=512,
        max_size=2 * 1024 * 1024 * 1024
    ),
]








class DiskScanner:
    """
    Scanner de disco para recuperação de arquivos
    Implementa file carving por assinatura binária
    """
    
    def __init__(self, read_only: bool = True):
        self.read_only = read_only
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self.results: List[ScanResult] = []
        self.last_scan_context: Dict = {}
        self.stats = {
            'bytes_scanned': 0,
            'files_found': 0,
            'start_time': None,
            'elapsed_time': 0
        }
        
    def stop(self):
        """Para a varredura"""
        self._stop_event.set()
        self._pause_event.set()  # Desbloqueia qualquer wait() ativo
        
    def pause(self):
        """Pausa a varredura"""
        self._pause_event.clear()
        
    def resume(self):
        """Retoma a varredura"""
        self._pause_event.set()
        
    def is_running(self) -> bool:
        """Verifica se a varredura está em execução"""
        return not self._stop_event.is_set()
    
    def is_paused(self) -> bool:
        """Verifica se a varredura está pausada"""
        return not self._pause_event.is_set()

    def _check_pause(self):
        """Aguarda se pausado; verifica stop a cada 500ms para evitar deadlock"""
        while not self._pause_event.is_set():
            if self._stop_event.is_set():
                return
            self._pause_event.wait(timeout=0.5)
        
    def scan_drive(self, 
                   drive_path: str,
                   mode: ScanMode = ScanMode.QUICK,
                   file_types: Optional[List[str]] = None,
                   progress_callback: Optional[Callable[[int, int, str], None]] = None,
                   sector_size: int = 512) -> List[ScanResult]:
        """
        Varre um drive ou pasta em busca de arquivos deletados.

        Se drive_path for um diretório existente, utiliza varredura por pasta
        (os.walk + assinatura binária de cada arquivo) em vez de acesso raw.
        """
        self.results = []
        self._stop_event.clear()
        self._pause_event.set()
        self.stats = {
            'bytes_scanned': 0,
            'files_found': 0,
            'start_time': time.time(),
            'elapsed_time': 0
        }
        drive_path = _sanitize_scan_target_path(drive_path)
        self.last_scan_context = get_scan_target_context(drive_path, mode)

        signatures = FILE_SIGNATURES
        if file_types:
            signatures = [s for s in signatures if s.extension in file_types]

        # ── Modo pasta: caminho é um diretório acessível ───────────────────────
        if os.path.isdir(drive_path):
            context = dict(self.last_scan_context)
            logger.info(
                "Modo pasta: varrendo '%s' (requested=%s effective=%s strategy=%s fs=%s)",
                drive_path,
                mode.value,
                context.get('effective_mode'),
                context.get('strategy'),
                context.get('filesystem'),
            )
            if context.get('effective_mode') == ScanMode.DEEP.value and context.get('strategy') == 'ntfs_mft':
                try:
                    self._scan_folder_deep_ntfs(drive_path, signatures, progress_callback, context)
                except PermissionError as exc:
                    logger.warning("Fallback da varredura profunda em pasta para modo acessível: %s", exc)
                    context.update({
                        'effective_mode': ScanMode.QUICK.value,
                        'strategy': 'filesystem_walk',
                        'note_code': 'folder_deep_permission_fallback',
                        'permission_fallback': True,
                    })
                    self.last_scan_context = context
                    self._scan_folder(drive_path, signatures, progress_callback)
            else:
                self._scan_folder(drive_path, signatures, progress_callback)
            self.stats['elapsed_time'] = time.time() - self.stats['start_time']
            logger.info(f"Varredura de pasta concluída. {len(self.results)} arquivos encontrados.")
            return self.results

        try:
            with self._open_scan_source(drive_path) as (drive, drive_size):
                logger.info(f"Iniciando varredura de {drive_path} ({self._format_size(drive_size)})")

                if mode == ScanMode.QUICK:
                    self._quick_scan(drive, drive_size, signatures, progress_callback, sector_size)
                else:
                    self._deep_scan(drive, drive_size, signatures, progress_callback, sector_size)

        except PermissionError:
            logger.error(f"Permissão negada para acessar {drive_path}. Execute como administrador.")
            raise
        except Exception as e:
            logger.error(f"Erro durante varredura: {e}")
            raise

        self.stats['elapsed_time'] = time.time() - self.stats['start_time']
        logger.info(f"Varredura concluída. {len(self.results)} arquivos encontrados em {self.stats['elapsed_time']:.2f}s")
        return self.results

    def get_last_scan_context(self) -> Dict:
        return dict(self.last_scan_context)

    @staticmethod
    def _is_windows_device_path(path: str) -> bool:
        """Distingue volumes/discos crus de arquivos comuns no Windows."""
        normalized = path.replace('/', '\\')
        if normalized.startswith(r'\\.\PHYSICALDRIVE'):
            return True
        return len(normalized) in (2, 3) and normalized[1] == ':' and (
            len(normalized) == 2 or normalized[2] == '\\'
        )

    def _scan_folder(self,
                     folder_path: str,
                     signatures: List[FileSignature],
                     progress_callback: Optional[Callable] = None) -> None:
        """
        Varre recursivamente uma pasta, identificando arquivos por assinatura binária.
        Realizada de modo reativo on-the-fly para prevenir atraso imediato (lag inicial).
        """
        logger.info(f"Modo pasta: varredura em tempo real iniciada em '{folder_path}'")

        file_counts = {'image': 0, 'video': 0, 'audio': 0, 'document': 0, 'archive': 0, 'other': 0}

        idx = 0
        for dirpath, dirnames, filenames in os.walk(folder_path):
            if self._stop_event.is_set():
                break

            # Filtra pastas inacessíveis sem disparar alertas (evita lentidão no log)
            accessible = []
            for d in dirnames:
                full = os.path.join(dirpath, d)
                try:
                    os.scandir(full).close()
                    accessible.append(d)
                except (PermissionError, OSError) as exc:
                    logger.debug("Ignorando subpasta inacessível %s: %s", full, exc)
            dirnames[:] = accessible

            for fn in filenames:
                if self._stop_event.is_set():
                    break
                self._check_pause()
                if self._stop_event.is_set():
                    break

                filepath = os.path.join(dirpath, fn)
                
                try:
                    file_size = os.path.getsize(filepath)
                    self.stats['bytes_scanned'] += file_size

                    with open(filepath, 'rb') as f:
                        header = f.read(32)

                    for sig in signatures:
                        matched = False
                        for magic in sig.signatures:
                            if header[:len(magic)] == magic:
                                result = ScanResult(
                                    offset=idx,
                                    size=file_size,
                                    file_type=sig.name,
                                    extension=sig.extension,
                                    confidence=0.9,
                                    signature_matched=magic.hex(),
                                    metadata={
                                        'original_path': filepath,
                                        'filename': fn,
                                    }
                                )
                                self.results.append(result)
                                self.stats['files_found'] += 1
                                cat = get_extension_category(sig.extension)
                                file_counts[cat] += 1
                                matched = True
                                break
                        if matched:
                            break

                except (PermissionError, OSError) as exc:
                    logger.debug("Ignorando arquivo inacessível %s: %s", filepath, exc)

                idx += 1
                if progress_callback and (idx % 10 == 0 or idx == 1):
                    # Progress callback emitido suavemente. Passamos 0 para o 'total' de
                    # arquivos ser tido como indeterminado (já que fluímos on-the-fly)
                    msg = (f"Analisando: {fn[:35]}... • "
                           f"{self.stats['files_found']} encontrados • "
                           f"Imagens: {file_counts['image']} • "
                           f"Vídeos: {file_counts['video']} • "
                           f"Áudios: {file_counts['audio']} • "
                           f"Docs: {file_counts['document']} • "
                           f"Arquivos: {file_counts['archive']}")
                    progress_callback(idx, 0, msg)

        if progress_callback and idx > 0:
            msg = (f"Varredura em pasta concluída • "
                   f"{self.stats['files_found']} encontrados • "
                   f"Imagens: {file_counts['image']} • "
                   f"Vídeos: {file_counts['video']} • "
                   f"Áudios: {file_counts['audio']} • "
                   f"Docs: {file_counts['document']} • "
                   f"Arquivos: {file_counts['archive']}")
            progress_callback(idx, idx, msg)

    def _scan_folder_deep_ntfs(
        self,
        folder_path: str,
        signatures: List[FileSignature],
        progress_callback: Optional[Callable] = None,
        context: Optional[Dict] = None,
    ) -> None:
        context = context or get_scan_target_context(folder_path, ScanMode.DEEP)
        source_device = context.get('volume_device') or folder_path
        mountpoint = context.get('volume_mountpoint') or Path(folder_path).anchor
        normalized_folder = _normalize_path_for_match(folder_path)
        normalized_mount = _normalize_path_for_match(mountpoint)
        relative_folder = normalized_folder[len(normalized_mount):].strip('\\/')
        folder_components = [part for part in relative_folder.split('\\') if part]
        signature_by_extension = {sig.extension.lower(): sig for sig in signatures}
        file_counts = {'image': 0, 'video': 0, 'audio': 0, 'document': 0, 'archive': 0, 'other': 0}

        with self._open_source_stream(source_device) as stream:
            volume_info = read_boot_sector(stream)
            if progress_callback:
                progress_callback(0, 0, "Lendo metadados NTFS ($MFT)...")

            records: Dict[int, object] = {}
            scanned_records = 0
            for record in iter_mft_records(stream, volume_info):
                if self._stop_event.is_set():
                    break
                self._check_pause()
                records[record.number] = record
                scanned_records += 1
                self.stats['bytes_scanned'] += volume_info.mft_record_size

                if progress_callback and (scanned_records == 1 or scanned_records % 256 == 0):
                    progress_callback(
                        scanned_records,
                        0,
                        f"Lendo metadados NTFS ($MFT)... {scanned_records} registros analisados • {self.stats['files_found']} encontrados",
                    )

            if self._stop_event.is_set():
                return

            build_full_paths(records)
            folder_record_number = resolve_folder_record(records, folder_components)
            if folder_record_number is None:
                if progress_callback:
                    progress_callback(scanned_records, scanned_records, "Pasta não localizada na árvore NTFS atual.")
                return

            descendants = collect_descendants(records, folder_record_number)

            for record_number in sorted(descendants):
                if self._stop_event.is_set():
                    break
                self._check_pause()
                record = records.get(record_number)
                if not record or record.is_directory or record.is_in_use or not record.name:
                    continue

                extension = record.name.rsplit('.', 1)[-1].lower() if '.' in record.name else ''
                signature = signature_by_extension.get(extension)
                if not signature:
                    continue
                if record.resident_data is None and not record.data_runs:
                    continue

                metadata = {
                    'original_path': mountpoint.rstrip('\\/') + ('\\' if record.full_path else '') + record.full_path,
                    'scan_source': 'ntfs_mft',
                    'source_device': source_device,
                    'filesystem': 'NTFS',
                    'record_number': record.number,
                    'deleted': True,
                    'cluster_size': volume_info.cluster_size,
                }

                is_fragmented = False
                offset = record.record_offset

                if record.resident_data is not None:
                    metadata['resident_data_b64'] = base64.b64encode(record.resident_data).decode('ascii')
                elif record.data_runs:
                    serialized_runs = []
                    for run in record.data_runs:
                        serialized_runs.append({
                            'lcn': run.lcn,
                            'length_clusters': run.length_clusters,
                        })
                    metadata['data_runs'] = serialized_runs
                    is_fragmented = len(record.data_runs) > 1
                    first_real_run = next((run for run in record.data_runs if run.lcn is not None and run.length_clusters > 0), None)
                    if first_real_run is not None:
                        offset = first_real_run.lcn * volume_info.cluster_size

                result = ScanResult(
                    offset=offset,
                    size=record.size,
                    file_type=signature.name,
                    extension=signature.extension,
                    confidence=0.94 if record.data_runs or record.resident_data is not None else 0.72,
                    signature_matched='ntfs:mft',
                    is_fragmented=is_fragmented,
                    metadata=metadata,
                )
                self.results.append(result)
                self.stats['files_found'] += 1
                category = get_extension_category(signature.extension)
                file_counts[category] = file_counts.get(category, 0) + 1

            if progress_callback:
                progress_callback(
                    scanned_records,
                    scanned_records,
                    (
                        f"Varredura profunda em pasta (NTFS) concluída • "
                        f"{self.stats['files_found']} encontrados • "
                        f"Imagens: {file_counts['image']} • "
                        f"Vídeos: {file_counts['video']} • "
                        f"Áudios: {file_counts['audio']} • "
                        f"Docs: {file_counts['document']} • "
                        f"Arquivos: {file_counts['archive']}"
                    ),
                )

    @staticmethod
    def _open_windows_drive(drive_path: str):
        """Abre um volume/disco no Windows usando a API nativa CreateFileW.
        
        Python open() não consegue abrir volumes crus no Windows pois não
        define as flags FILE_SHARE_READ|WRITE corretamente. Usar CreateFileW
        via ctypes é obrigatório para leitura de disco em baixo nível.
        """
        import ctypes
        import ctypes.wintypes as wintypes
        import msvcrt

        kernel32 = ctypes.windll.kernel32

        GENERIC_READ      = 0x80000000
        FILE_SHARE_READ   = 0x00000001
        FILE_SHARE_WRITE  = 0x00000002
        OPEN_EXISTING     = 3
        FILE_ATTRIBUTE_NORMAL = 0x80
        INVALID_HANDLE    = wintypes.HANDLE(-1).value

        # Define tipos exatos para prevenir Pointer Truncation e Access Violation fatal em x64
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE

        kernel32.DeviceIoControl.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
        ]
        kernel32.DeviceIoControl.restype = wintypes.BOOL

        handle = kernel32.CreateFileW(
            drive_path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None
        )

        if handle == INVALID_HANDLE or handle == -1:
            err = ctypes.get_last_error() or ctypes.GetLastError()
            if err == 5:
                raise PermissionError(f"Acesso negado a {drive_path}. Execute como Administrador.")
            raise OSError(f"CreateFileW falhou para {drive_path} (erro Windows {err})")

        # Obtém tamanho real do volume via IOCTL
        IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
        
        class DISK_LENGTH_INFO(ctypes.Structure):
            _fields_ = [("Length", ctypes.c_longlong)]

        length_info = DISK_LENGTH_INFO()
        bytes_returned = wintypes.DWORD(0)
        
        ok = kernel32.DeviceIoControl(
            handle,
            IOCTL_DISK_GET_LENGTH_INFO,
            None, 0,
            ctypes.byref(length_info), ctypes.sizeof(length_info),
            ctypes.byref(bytes_returned),
            None
        )

        if ok:
            drive_size = length_info.Length
        else:
            # Fallback: utiliza psutil para o tamanho
            try:
                import psutil
                letter = drive_path[-2:]  # ex: 'C:'
                for part in psutil.disk_partitions():
                    if part.device.startswith(letter):
                        usage = psutil.disk_usage(part.mountpoint)
                        drive_size = usage.total
                        break
                else:
                    drive_size = 0
            except Exception:
                drive_size = 0

        # Converte handle Win32 → fd → Python file object
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        drive_file = os.fdopen(fd, 'rb')

        return drive_file, drive_size

    @contextmanager
    def _open_scan_source(self, drive_path: str):
        """Abre a origem da varredura com fechamento garantido do handle."""
        if os.name == 'nt' and self._is_windows_device_path(drive_path):
            normalized_path = drive_path
            if len(normalized_path) == 2 and normalized_path[1] == ':':
                normalized_path = r'\\.' + '\\' + normalized_path
            elif len(normalized_path) == 3 and normalized_path[1] == ':' and normalized_path[2] in ('\\', '/'):
                normalized_path = r'\\.' + '\\' + normalized_path[:2]
            drive, drive_size = self._open_windows_drive(normalized_path)
            try:
                yield drive, drive_size
            finally:
                drive.close()
            return

        mode_flag = 'rb' if self.read_only else 'rb+'
        with open(drive_path, mode_flag) as drive:
            drive.seek(0, 2)
            drive_size = drive.tell()
            drive.seek(0)
            yield drive, drive_size

    def _open_source_stream(self, source_path: str):
        """Abre arquivo comum, volume cru ou imagem de forma uniforme."""
        if os.name == 'nt' and self._is_windows_device_path(source_path):
            normalized = source_path
            if len(normalized) == 2 and normalized[1] == ':':
                normalized = r'\\.' + '\\' + normalized
            elif len(normalized) == 3 and normalized[1] == ':' and normalized[2] in ('\\', '/'):
                normalized = r'\\.' + '\\' + normalized[:2]
            drive_file, _ = self._open_windows_drive(normalized)
            return drive_file
        return open_binary_stream(source_path)
    
    def _aligned_read(self, drive, offset: int, size: int, sector_size: int = 512) -> bytes:
        """Lê dados de volume cru com alinhamento de setor obrigatório (Windows)"""
        aligned_offset = (offset // sector_size) * sector_size
        end = offset + size
        aligned_end = ((end + sector_size - 1) // sector_size) * sector_size
        aligned_size = aligned_end - aligned_offset
        
        try:
            drive.seek(aligned_offset)
            raw = drive.read(aligned_size)
        except OSError:
            return b''
        
        # Retorna apenas os bytes solicitados
        skip = offset - aligned_offset
        return raw[skip:skip + size]
        
    def _quick_scan(self,
                    drive,
                    drive_size: int,
                    signatures: list,
                    progress_callback,
                    sector_size: int):
        """
        Varredura rápida — mmap + single-pass greedy match.

        Melhorias vs versão anterior:
        - Tenta usar mmap (zero-copy, SO lida com paginação) quando possível
        - Para dispositivos RAW do Windows (que não suportam mmap), usa leitura
          alinhada com chunks de 16 MB (era 4 MB) para ~4× menos syscalls
        - Busca greedy single-pass: find() mais barato que loop nested
        - Padrões ordenados por comprimento desc para matches mais específicos primeiro
        """
        CHUNK   = 16 * 1024 * 1024   # 16 MB — sweet spot para HDDs e SSDs
        CHUNK   = (CHUNK // sector_size) * sector_size
        max_sig = max((len(pattern) for sig in signatures for pattern in sig.signatures), default=16)
        OVERLAP = ((max_sig + 16 + sector_size - 1) // sector_size) * sector_size

        file_counts = {'image':0,'video':0,'audio':0,'document':0,'archive':0,'other':0}

        # Pre-build flat sig list ONCE — sorted by pattern length desc
        flat_sigs = []
        for sig in signatures:
            min_skip = max(sig.min_size, sector_size * 4)
            for pattern in sig.signatures:
                flat_sigs.append((pattern, sig, min_skip))
        flat_sigs.sort(key=lambda x: len(x[0]), reverse=True)

        # ── Tenta mmap (zero-copy) ────────────────────────────────────────────
        # mmap funciona em arquivos normais e imagens de disco; não funciona em
        # handles de dispositivo RAW do Windows (PHYSICALDRIVE) — nesse caso,
        # cairemos no loop de leitura alinhada abaixo.
        use_mmap = False
        mm = None
        try:
            fileno = drive.fileno()
            mm = mmap.mmap(fileno, 0, access=mmap.ACCESS_READ)
            use_mmap = True
            logger.debug("_quick_scan: usando mmap (zero-copy)")
        except (AttributeError, OSError, ValueError):
            logger.debug("_quick_scan: mmap indisponível, usando leitura alinhada 16MB")

        def _process_buffer(search_buf: bytes, buf_base: int, current_pos: int):
            """Executa o single-pass greedy match num buffer já carregado."""
            buf_pos = 0
            buf_len = len(search_buf)
            while buf_pos < buf_len:
                best_pos    = -1
                best_pat    = b''
                best_obj    = None
                best_skip   = sector_size * 4

                for pattern, sig, min_skip in flat_sigs:
                    found = search_buf.find(pattern, buf_pos)
                    if found == -1:
                        continue
                    if best_pos == -1 or found < best_pos or \
                       (found == best_pos and len(pattern) > len(best_pat)):
                        best_pos  = found
                        best_pat  = pattern
                        best_obj  = sig
                        best_skip = min_skip

                if best_pos == -1:
                    break

                absolute_pos = buf_base + best_pos
                if absolute_pos >= current_pos and best_obj is not None:
                    file_size = self._estimate_quick_file_size(
                        drive,
                        start_offset=absolute_pos,
                        signature=best_obj,
                        drive_size=drive_size,
                    )
                    result = ScanResult(
                        offset=absolute_pos, size=file_size,
                        file_type=best_obj.name, extension=best_obj.extension,
                        confidence=0.65, signature_matched=best_pat.hex()
                    )
                    self.results.append(result)
                    self.stats['files_found'] += 1
                    cat = get_extension_category(best_obj.extension)
                    file_counts[cat] = file_counts.get(cat, 0) + 1

                buf_pos = best_pos + best_skip

        try:
            if use_mmap and mm is not None:
                # ── Caminho mmap: percorre com views, sem alocação extra ──────
                current_pos = 0
                while current_pos < drive_size and not self._stop_event.is_set():
                    self._check_pause()
                    if self._stop_event.is_set():
                        break

                    chunk_end  = min(current_pos + CHUNK + OVERLAP, drive_size)
                    read_start = max(0, current_pos - OVERLAP)
                    buf_base   = read_start
                    search_buf = mm[read_start:chunk_end]   # slice → view, no copy

                    _process_buffer(search_buf, buf_base, current_pos)

                    read_amt = min(CHUNK, drive_size - current_pos)
                    self.stats['bytes_scanned'] += read_amt
                    current_pos += read_amt

                    if progress_callback:
                        pct_msg = (
                            f"Varredura rápida: {len(self.results)} encontrados \u2022 "
                            f"Imagens: {file_counts['image']} | Vídeos: {file_counts['video']} | "
                            f"Docs: {file_counts['document']} | Áudios: {file_counts['audio']} | "
                            f"Arquivos: {file_counts['archive']}"
                        )
                        progress_callback(current_pos, drive_size, pct_msg)

            else:
                # ── Caminho leitura alinhada (dispositivos RAW Windows) ───────
                current_pos = 0
                prev_tail   = b''
                while current_pos < drive_size and not self._stop_event.is_set():
                    self._check_pause()
                    if self._stop_event.is_set():
                        break

                    remaining = drive_size - current_pos
                    read_size = min(CHUNK, remaining)
                    read_size = (read_size // sector_size) * sector_size
                    if read_size == 0:
                        break

                    try:
                        drive.seek(current_pos)
                        chunk = drive.read(read_size)
                    except OSError:
                        current_pos += sector_size
                        continue

                    if not chunk:
                        break

                    search_buf = prev_tail + chunk
                    buf_base   = current_pos - len(prev_tail)

                    _process_buffer(search_buf, buf_base, current_pos)

                    self.stats['bytes_scanned'] += len(chunk)
                    current_pos += len(chunk)
                    prev_tail = chunk[-OVERLAP:] if len(chunk) > OVERLAP else chunk

                    if progress_callback:
                        pct_msg = (
                            f"Varredura rápida: {len(self.results)} encontrados \u2022 "
                            f"Imagens: {file_counts['image']} | Vídeos: {file_counts['video']} | "
                            f"Docs: {file_counts['document']} | Áudios: {file_counts['audio']} | "
                            f"Arquivos: {file_counts['archive']}"
                        )
                        progress_callback(current_pos, drive_size, pct_msg)

        finally:
            if mm is not None:
                try:
                    mm.close()
                except (BufferError, ValueError) as exc:
                    logger.debug("Falha ao fechar mmap da varredura: %s", exc)


    def _deep_scan(self,
                   drive,
                   drive_size: int,
                   signatures: List[FileSignature],
                   progress_callback: Optional[Callable],
                   sector_size: int):
        """Varredura profunda com overlap entre chunks e checagem byte a byte."""
        chunk_size = max((2 * 1024 * 1024 // sector_size) * sector_size, sector_size)
        max_sig_len = max((len(pattern) for sig in signatures for pattern in sig.signatures), default=16)
        overlap = max_sig_len - 1

        file_counts = {'image': 0, 'video': 0, 'audio': 0, 'document': 0, 'archive': 0, 'other': 0}

        current_pos = 0
        prev_tail = b''

        while current_pos < drive_size and not self._stop_event.is_set():
            self._check_pause()
            read_size = min(chunk_size, drive_size - current_pos)
            read_size = (read_size // sector_size) * sector_size
            if read_size == 0:
                break

            try:
                drive.seek(current_pos)
                chunk = drive.read(read_size)
            except OSError:
                current_pos += sector_size
                continue

            if not chunk:
                break

            search_buffer = prev_tail + chunk
            buffer_base = current_pos - len(prev_tail)
            last_start = max(len(search_buffer) - max_sig_len + 1, 0)
            skip_until = current_pos

            for i in range(last_start):
                absolute_pos = buffer_base + i
                if absolute_pos < current_pos or absolute_pos < skip_until:
                    continue

                for sig in signatures:
                    matched_signature = None
                    for signature in sig.signatures:
                        sig_len = len(signature)
                        if i + sig_len <= len(search_buffer) and search_buffer[i:i+sig_len] == signature:
                            matched_signature = signature
                            break

                    if not matched_signature:
                        continue

                    file_size = self._estimate_file_size(drive, absolute_pos, sig, drive_size)
                    confidence = self._calculate_confidence(drive, absolute_pos, sig, file_size)
                    result = ScanResult(
                        offset=absolute_pos,
                        size=file_size,
                        file_type=sig.name,
                        extension=sig.extension,
                        confidence=confidence,
                        signature_matched=matched_signature.hex()
                    )
                    self.results.append(result)
                    self.stats['files_found'] += 1
                    cat = get_extension_category(sig.extension)
                    file_counts[cat] = file_counts.get(cat, 0) + 1
                    skip_until = absolute_pos + max(
                        len(matched_signature),
                        min(file_size, max(sig.min_size, sector_size * 4))
                    )
                    break

            self.stats['bytes_scanned'] += len(chunk)
            current_pos += len(chunk)
            prev_tail = search_buffer[-overlap:] if overlap else b''

            if progress_callback:
                pct_msg = (
                    f"Varredura profunda: {len(self.results)} encontrados • "
                    f"Imagens: {file_counts['image']} | Vídeos: {file_counts['video']} | "
                    f"Docs: {file_counts['document']} | Áudios: {file_counts['audio']} | "
                    f"Arquivos: {file_counts['archive']}"
                )
                progress_callback(current_pos, drive_size, pct_msg)

    def _estimate_quick_file_size(self,
                                  drive,
                                  start_offset: int,
                                  signature: FileSignature,
                                  drive_size: int) -> int:
        """Usa heurística rápida menos agressiva para evitar truncamentos óbvios."""
        max_scan = min(signature.max_size, drive_size - start_offset)
        if max_scan <= 0:
            return 0

        if signature.footers:
            estimated = self._estimate_file_size(drive, start_offset, signature, drive_size)
            if estimated and 0 < estimated <= max_scan:
                return estimated

        header = self._aligned_read(drive, start_offset, 512)
        estimated = self._extract_size_from_header(header, signature)
        if estimated and 0 < estimated <= max_scan:
            return estimated

        category = get_extension_category(signature.extension)
        default_sizes = {
            'image': 8 * 1024 * 1024,
            'video': 128 * 1024 * 1024,
            'audio': 32 * 1024 * 1024,
            'document': 8 * 1024 * 1024,
            'archive': 32 * 1024 * 1024,
            'other': 4 * 1024 * 1024,
        }
        fallback_size = max(signature.min_size, default_sizes.get(category, default_sizes['other']))
        return min(fallback_size, max_scan)
    
    def _estimate_file_size(self,
                           drive,
                           start_offset: int,
                           signature: FileSignature,
                           drive_size: int) -> int:
        """Estima o tamanho de um arquivo encontrado"""
        max_scan = min(signature.max_size, drive_size - start_offset)
        
        # Se tem footer definido, procura por ele
        if signature.footers:
            chunk_size = 64 * 1024
            scanned = 0
            valid_footers = [footer for footer in signature.footers if isinstance(footer, (bytes, bytearray)) and footer]
            if not valid_footers:
                valid_footers = []
            
            while scanned < max_scan:
                chunk = self._aligned_read(drive, start_offset + scanned, min(chunk_size, max_scan - scanned))
                
                if not chunk:
                    break
                
                for footer in valid_footers:
                    pos = chunk.find(footer)
                    if pos != -1:
                        return scanned + pos + len(footer)

                overlap = len(max(valid_footers, key=len)) if valid_footers else 0
                advance = len(chunk) - overlap
                if advance <= 0:
                    break
                scanned += advance
        
        # Se não achou footer, usa heurísticas
        header = self._aligned_read(drive, start_offset, 512)
        
        # Tenta extrair tamanho do header para formatos conhecidos
        estimated_size = self._extract_size_from_header(header, signature)
        
        if estimated_size and estimated_size < max_scan:
            return estimated_size
        
        # Fallback: tamanho padrão baseado no tipo
        return min(1024 * 1024, max_scan)  # 1MB padrão
    
    def _extract_size_from_header(self, header: bytes, signature: FileSignature) -> Optional[int]:
        """Extrai tamanho do arquivo do header para formatos específicos"""
        try:
            if signature.extension in ['jpg', 'jpeg']:
                # Procura por segmentos JPEG
                i = 2
                while i < len(header) - 2:
                    marker = header[i]
                    if marker == 0xFF:
                        marker_type = header[i + 1]
                        if marker_type == 0xD9:  # EOI
                            return i + 2
                        elif marker_type in [0xD8, 0xD9, 0x00]:
                            i += 2
                        elif marker_type in [0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7]:
                            i += 2
                        else:
                            length = struct.unpack('>H', header[i+2:i+4])[0]
                            i += 2 + length
                    else:
                        i += 1
                        
            elif signature.extension == 'png':
                # PNG: procura chunk IEND
                if b'IEND' in header:
                    i = header.find(b'IEND')
                    return i + 8  # IEND + CRC
                    
            elif signature.extension == 'gif':
                # GIF: procura trailer
                if b'\x00\x3b' in header:
                    return header.find(b'\x00\x3b') + 2
                    
            elif signature.extension == 'zip':
                # ZIP: procura EOCD
                if b'PK\x05\x06' in header:
                    return header.find(b'PK\x05\x06') + 22
                    
        except (IndexError, struct.error, ValueError) as exc:
            logger.debug("Falha ao estimar tamanho pelo header para %s: %s", signature.extension, exc)
            
        return None
    
    def _calculate_confidence(self,
                             drive,
                             offset: int,
                             signature: FileSignature,
                             estimated_size: int) -> float:
        """Calcula confiança da recuperação (0.0 a 1.0)"""
        confidence = 0.5  # Base
        
        # Verifica se o tamanho está dentro dos limites
        if signature.min_size <= estimated_size <= signature.max_size:
            confidence += 0.2
        
        # Verifica footer se disponível
        if signature.footers:
            tail = self._aligned_read(drive, offset + estimated_size - 100, 100)
            for footer in signature.footers:
                if footer in tail:
                    confidence += 0.3
                    break
        
        # Verifica integridade do header
        header = self._aligned_read(drive, offset, 512)
        if self._verify_header_integrity(header, signature):
            confidence += 0.2
        
        return min(confidence, 1.0)
    
    def _verify_header_integrity(self, header: bytes, signature: FileSignature) -> bool:
        """Verifica integridade básica do header"""
        if len(header) < 8:
            return False
            
        # Verificações específicas por formato
        if signature.extension in ['jpg', 'jpeg']:
            return header[0:2] == b'\xff\xd8'
        elif signature.extension == 'png':
            return header[0:8] == b'\x89PNG\r\n\x1a\n'
        elif signature.extension == 'pdf':
            return header[0:4] == b'%PDF'
        elif signature.extension in ['docx', 'xlsx', 'pptx']:
            return header[0:4] == b'PK\x03\x04'
            
        return True
    
    def _format_size(self, size_bytes: int) -> str:
        """Formata tamanho em bytes para string legível"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.2f} PB"
    
    def get_stats(self) -> Dict:
        """Retorna estatísticas da varredura"""
        stats = self.stats.copy()
        if stats['start_time']:
            stats['elapsed_time'] = time.time() - stats['start_time']
        return stats


def get_available_drives() -> List[Dict]:
    """Retorna lista de drives disponíveis no sistema"""
    drives = []
    system_drive = os.environ.get('SystemDrive', 'C:').upper()
    system_root = Path(os.environ.get('SystemRoot', os.sep)).anchor.upper() if os.name == 'nt' else '/'
    
    try:
        import psutil
        
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                drives.append({
                    'device': partition.device,
                    'mountpoint': partition.mountpoint,
                    'fstype': partition.fstype,
                    'opts': partition.opts,
                    'total': usage.total,
                    'used': usage.used,
                    'free': usage.free,
                    'percent': usage.percent,
                    'is_system': _is_system_partition(partition.mountpoint, system_drive, system_root),
                })
            except PermissionError:
                drives.append({
                    'device': partition.device,
                    'mountpoint': partition.mountpoint,
                    'fstype': partition.fstype,
                    'opts': partition.opts,
                    'total': 0,
                    'used': 0,
                    'free': 0,
                    'percent': 0,
                    'error': 'Permission denied',
                    'is_system': _is_system_partition(partition.mountpoint, system_drive, system_root),
                })
    except ImportError:
        logger.warning("psutil não instalado. Usando método alternativo.")
        
        # Windows
        if os.name == 'nt':
            import string
            import ctypes
            
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drive_path = f"{letter}:\\"
                    drives.append({
                        'device': drive_path,
                        'mountpoint': drive_path,
                        'fstype': 'unknown',
                        'opts': '',
                        'total': 0,
                        'used': 0,
                        'free': 0,
                        'percent': 0,
                        'is_system': _is_system_partition(drive_path, system_drive, system_root),
                    })
                bitmask >>= 1
    
    return drives


def _is_system_partition(mountpoint: str, system_drive: str, system_root: str) -> bool:
    normalized = (mountpoint or '').replace('/', '\\').rstrip('\\').upper()
    if os.name == 'nt':
        return bool(normalized) and normalized == system_drive.rstrip('\\').upper()
    return (mountpoint or '/') == system_root


if __name__ == '__main__':
    # Teste do scanner
    logging.basicConfig(level=logging.INFO)
    
    print("Drives disponíveis:")
    for drive in get_available_drives():
        print(f"  {drive['device']} - {drive['mountpoint']} ({drive.get('fstype', 'unknown')})")
