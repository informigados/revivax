"""
RevivaX — Web Application (API Flask)
Versão limpa pós-auditoria: imports deduplicados, CORS restrito ao localhost,
thread-lock no scan_progress, SMART com cache TTL, segurança melhorada.
"""

import os
import re
import sys
import csv
import json
import logging
import subprocess as sp
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from flask import Flask, Response, render_template, jsonify, request, send_file
from flask_cors import CORS

# Adiciona raiz ao path para importar core
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import (
    CarveResult, RecoveryManager, RecoveryStatus, ScanMode,
    SMARTMonitor, get_extension_category, get_smart_monitor, get_recovery_manager
)
from core.runtime_paths import get_logs_dir

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


def _get_allowed_local_origins() -> List[str]:
    """
    Define uma allowlist explícita de origens locais para CORS.

    O fluxo padrão da UI é same-origin e não depende de CORS. Esta lista só
    libera integrações locais controladas.
    """
    configured = os.environ.get('REVIVAX_ALLOWED_ORIGINS', '').strip()
    if configured:
        return [origin.strip() for origin in configured.split(',') if origin.strip()]
    return [
        'http://127.0.0.1:5000',
        'http://localhost:5000',
        'http://127.0.0.1:8000',
        'http://localhost:8000',
    ]


LOCAL_ALLOWED_ORIGINS = _get_allowed_local_origins()

# ── Flask app ─────────────────────────────────────────────────────────────────
def resource_path(relative_path: str) -> str:
    """Resolve caminho absoluto de recursos, compatível com PyInstaller e modo dev."""
    try:
        base = sys._MEIPASS           # PyInstaller bundle
    except AttributeError:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)

app = Flask(
    __name__,
    template_folder=resource_path('templates'),
    static_folder=resource_path('static'),
)

# CORS restrito: apenas origens locais explicitamente permitidas.
CORS(app, resources={r'/api/*': {'origins': LOCAL_ALLOWED_ORIGINS}})

# Configurações básicas
app.config['SECRET_KEY']          = os.environ.get('REVIVAX_SECRET', 'revivax-local-secret-key')
app.config['MAX_CONTENT_LENGTH']  = 16 * 1024 * 1024  # 16 MB
app.config['JSON_ENSURE_ASCII']   = False              # Suporte a UTF-8 no JSON

_CSP_POLICY = '; '.join([
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "connect-src 'self'",
    "img-src 'self' data:",
    "style-src 'self' 'unsafe-inline'",
    "script-src 'self' 'unsafe-inline'",
    "font-src 'self' data:",
])

# ── Instâncias globais ─────────────────────────────────────────────────────────
recovery_manager: Optional[RecoveryManager] = None
smart_monitor:    Optional[SMARTMonitor]    = None

# ── Estado de progresso (protegido por lock) ───────────────────────────────────
_progress_lock = threading.Lock()
_PROGRESS_EMPTY = {
    'current':     0,
    'total':       0,
    'message':     '',
    'status':      'idle',
    'job_id':      None,
    'files_found': 0,
    'file_counts': {
        'image': 0, 'video': 0, 'audio': 0,
        'document': 0, 'archive': 0, 'other': 0,
    },
}
scan_progress: dict = {**_PROGRESS_EMPTY}

# ── Cache de dados SMART (evita múltiplos round-trips ao PS) ──────────────────
_smart_cache_state = {
    'data': None,
    'time': 0.0,
}
_SMART_CACHE_TTL_SECS: int            = 60   # Reutiliza dados por 60 s

API_TRANSLATIONS = {
    'pt-BR': {
        'common.error_with_message': 'Erro: {message}',
        'common.internal_error': 'Erro interno. Consulte os logs com o código {incident}.',
        'smart.unavailable': 'SMART indisponível. Instale o smartmontools para dados completos.',
        'smart.cache_cleared': 'Cache SMART invalidado.',
        'smart.unavailable_short': 'SMART indisponível',
        'smart.invalid_device_path': 'Caminho de dispositivo inválido.',
        'smart.info_unavailable': 'Informações SMART não disponíveis.',
        'scan.drive_missing': 'Drive não especificado.',
        'scan.invalid_target': 'Alvo de varredura inválido ou não suportado.',
        'scan.system_unavailable': 'Sistema de recuperação não inicializado.',
        'scan.starting': 'Iniciando varredura...',
        'scan.completed': 'Varredura concluída: {count} arquivo(s) encontrado(s).',
        'scan.started': 'Varredura iniciada.',
        'scan.stopped_by_user': 'Varredura interrompida pelo usuário.',
        'scan.stopped': 'Varredura interrompida.',
        'scan.paused': 'Varredura pausada.',
        'scan.resumed': 'Varredura retomada.',
        'recover.no_scan_results': 'Nenhum resultado de varredura disponível.',
        'recover.no_selection': 'Nenhum arquivo selecionado para recuperação.',
        'recover.invalid_output_dir': 'Diretório de saída inválido.',
        'recover.protected_output_dir': 'O diretório escolhido é protegido pelo sistema. Escolha outro local.',
        'recover.restricted_output_dir': 'Diretório de saída restrito por segurança.',
        'recover.internal_failure': 'Falha interna (STAB-01): {message}',
        'recover.started': 'Recuperação iniciada: {count} arquivo(s).',
        'estimate.drive_missing': 'Drive não especificado.',
        'logs.invalid_filename': 'Nome de arquivo inválido.',
        'logs.not_found': 'Log não encontrado.',
        'export.no_scan': 'Nenhuma varredura disponível para exportar.',
        'export.unsupported_format': 'Formato "{format}" não suportado.',
        'export.csv.offset': 'Deslocamento',
        'export.csv.size': 'Tamanho',
        'export.csv.type': 'Tipo',
        'export.csv.extension': 'Extensão',
        'export.csv.confidence': 'Confiança',
        'browse.windows_only': 'Seletor nativo disponível apenas no Windows.',
        'browse.dialog_title': 'Selecione a pasta para varredura',
        'download.invalid_filename': 'Nome de arquivo inválido.',
        'download.not_found': 'Arquivo não encontrado.',
    },
    'en': {
        'common.error_with_message': 'Error: {message}',
        'common.internal_error': 'Internal error. Check the logs with code {incident}.',
        'smart.unavailable': 'SMART unavailable. Install smartmontools for full data.',
        'smart.cache_cleared': 'SMART cache cleared.',
        'smart.unavailable_short': 'SMART unavailable',
        'smart.invalid_device_path': 'Invalid device path.',
        'smart.info_unavailable': 'SMART information unavailable.',
        'scan.drive_missing': 'Drive not specified.',
        'scan.invalid_target': 'Invalid or unsupported scan target.',
        'scan.system_unavailable': 'Recovery system not initialized.',
        'scan.starting': 'Starting scan...',
        'scan.completed': 'Scan completed: {count} file(s) found.',
        'scan.started': 'Scan started.',
        'scan.stopped_by_user': 'Scan stopped by the user.',
        'scan.stopped': 'Scan stopped.',
        'scan.paused': 'Scan paused.',
        'scan.resumed': 'Scan resumed.',
        'recover.no_scan_results': 'No scan results available.',
        'recover.no_selection': 'No files selected for recovery.',
        'recover.invalid_output_dir': 'Invalid output directory.',
        'recover.protected_output_dir': 'The selected directory is protected by the system. Choose another location.',
        'recover.restricted_output_dir': 'Output directory restricted for security reasons.',
        'recover.internal_failure': 'Internal failure (STAB-01): {message}',
        'recover.started': 'Recovery started: {count} file(s).',
        'estimate.drive_missing': 'Drive not specified.',
        'logs.invalid_filename': 'Invalid file name.',
        'logs.not_found': 'Log not found.',
        'export.no_scan': 'No scan available for export.',
        'export.unsupported_format': 'Format "{format}" is not supported.',
        'export.csv.offset': 'Offset',
        'export.csv.size': 'Size',
        'export.csv.type': 'Type',
        'export.csv.extension': 'Extension',
        'export.csv.confidence': 'Confidence',
        'browse.windows_only': 'Native picker is only available on Windows.',
        'browse.dialog_title': 'Select the folder to scan',
        'download.invalid_filename': 'Invalid file name.',
        'download.not_found': 'File not found.',
    },
    'pt-PT': {
        'common.error_with_message': 'Erro: {message}',
        'common.internal_error': 'Erro interno. Consulte os registos com o código {incident}.',
        'smart.unavailable': 'SMART indisponível. Instale o smartmontools para dados completos.',
        'smart.cache_cleared': 'Cache SMART invalidada.',
        'smart.unavailable_short': 'SMART indisponível',
        'smart.invalid_device_path': 'Caminho do dispositivo inválido.',
        'smart.info_unavailable': 'Informações SMART indisponíveis.',
        'scan.drive_missing': 'Unidade não especificada.',
        'scan.invalid_target': 'Destino de análise inválido ou não suportado.',
        'scan.system_unavailable': 'Sistema de recuperação não inicializado.',
        'scan.starting': 'A iniciar análise...',
        'scan.completed': 'Análise concluída: {count} ficheiro(s) encontrado(s).',
        'scan.started': 'Análise iniciada.',
        'scan.stopped_by_user': 'Análise interrompida pelo utilizador.',
        'scan.stopped': 'Análise interrompida.',
        'scan.paused': 'Análise em pausa.',
        'scan.resumed': 'Análise retomada.',
        'recover.no_scan_results': 'Nenhum resultado de análise disponível.',
        'recover.no_selection': 'Nenhum ficheiro selecionado para recuperação.',
        'recover.invalid_output_dir': 'Diretório de saída inválido.',
        'recover.protected_output_dir': 'O diretório selecionado está protegido pelo sistema. Escolha outro local.',
        'recover.restricted_output_dir': 'Diretório de saída restrito por segurança.',
        'recover.internal_failure': 'Falha interna (STAB-01): {message}',
        'recover.started': 'Recuperação iniciada: {count} ficheiro(s).',
        'estimate.drive_missing': 'Unidade não especificada.',
        'logs.invalid_filename': 'Nome de ficheiro inválido.',
        'logs.not_found': 'Registo não encontrado.',
        'export.no_scan': 'Nenhuma análise disponível para exportação.',
        'export.unsupported_format': 'O formato "{format}" não é suportado.',
        'export.csv.offset': 'Deslocamento',
        'export.csv.size': 'Tamanho',
        'export.csv.type': 'Tipo',
        'export.csv.extension': 'Extensão',
        'export.csv.confidence': 'Confiança',
        'browse.windows_only': 'O seletor nativo só está disponível no Windows.',
        'browse.dialog_title': 'Selecione a pasta para analisar',
        'download.invalid_filename': 'Nome de ficheiro inválido.',
        'download.not_found': 'Ficheiro não encontrado.',
    },
    'es': {
        'common.error_with_message': 'Error: {message}',
        'common.internal_error': 'Error interno. Revise los registros con el código {incident}.',
        'smart.unavailable': 'SMART no disponible. Instale smartmontools para obtener todos los datos.',
        'smart.cache_cleared': 'Caché SMART invalidada.',
        'smart.unavailable_short': 'SMART no disponible',
        'smart.invalid_device_path': 'Ruta de dispositivo no válida.',
        'smart.info_unavailable': 'Información SMART no disponible.',
        'scan.drive_missing': 'Unidad no especificada.',
        'scan.invalid_target': 'Destino de escaneo no válido o no compatible.',
        'scan.system_unavailable': 'Sistema de recuperación no inicializado.',
        'scan.starting': 'Iniciando escaneo...',
        'scan.completed': 'Escaneo completado: {count} archivo(s) encontrado(s).',
        'scan.started': 'Escaneo iniciado.',
        'scan.stopped_by_user': 'Escaneo detenido por el usuario.',
        'scan.stopped': 'Escaneo detenido.',
        'scan.paused': 'Escaneo en pausa.',
        'scan.resumed': 'Escaneo reanudado.',
        'recover.no_scan_results': 'No hay resultados de escaneo disponibles.',
        'recover.no_selection': 'No se seleccionaron archivos para recuperar.',
        'recover.invalid_output_dir': 'Directorio de salida no válido.',
        'recover.protected_output_dir': 'El directorio seleccionado está protegido por el sistema. Elija otra ubicación.',
        'recover.restricted_output_dir': 'Directorio de salida restringido por seguridad.',
        'recover.internal_failure': 'Fallo interno (STAB-01): {message}',
        'recover.started': 'Recuperación iniciada: {count} archivo(s).',
        'estimate.drive_missing': 'Unidad no especificada.',
        'logs.invalid_filename': 'Nombre de archivo no válido.',
        'logs.not_found': 'Registro no encontrado.',
        'export.no_scan': 'No hay un escaneo disponible para exportar.',
        'export.unsupported_format': 'El formato "{format}" no es compatible.',
        'export.csv.offset': 'Desplazamiento',
        'export.csv.size': 'Tamaño',
        'export.csv.type': 'Tipo',
        'export.csv.extension': 'Extensión',
        'export.csv.confidence': 'Confianza',
        'browse.windows_only': 'El selector nativo solo está disponible en Windows.',
        'browse.dialog_title': 'Seleccione la carpeta para escanear',
        'download.invalid_filename': 'Nombre de archivo no válido.',
        'download.not_found': 'Archivo no encontrado.',
    },
}

_FOUND_PATTERNS = (
    r'(\d+)\s+encontrados?',
    r'(\d+)\s+found',
    r'(\d+)\s+ficheiro(?:s)?\s+encontrado(?:s)?',
    r'(\d+)\s+archivo(?:s)?\s+encontrado(?:s)?',
)

_CATEGORY_PATTERNS = {
    'image': (
        r'Imagens:\s*(\d+)',
        r'Images:\s*(\d+)',
        r'Imágenes:\s*(\d+)',
    ),
    'video': (
        r'Vídeos:\s*(\d+)',
        r'Videos:\s*(\d+)',
        r'V[ií]deos:\s*(\d+)',
    ),
    'audio': (
        r'Áudios:\s*(\d+)',
        r'Audio:\s*(\d+)',
        r'Áudio:\s*(\d+)',
    ),
    'document': (
        r'Docs:\s*(\d+)',
        r'Documents:\s*(\d+)',
        r'Documentos:\s*(\d+)',
        r'Documentos?:\s*(\d+)',
    ),
    'archive': (
        r'Arquivos:\s*(\d+)',
        r'Archives:\s*(\d+)',
        r'Archivos:\s*(\d+)',
    ),
}


def init_managers() -> None:
    """Inicializa gerenciadores de recuperação e monitoramento."""
    global recovery_manager, smart_monitor
    recovery_manager = get_recovery_manager()
    smart_monitor    = get_smart_monitor()
    logger.info("Gerenciadores inicializados com sucesso.")


def _get_request_lang() -> str:
    raw = (request.headers.get('X-RevivaX-Lang')
           or request.headers.get('Accept-Language')
           or '').strip()
    raw = raw.split(',')[0].strip()
    if raw.startswith('pt-PT'):
        return 'pt-PT'
    if raw.startswith('pt'):
        return 'pt-BR'
    if raw.startswith('es'):
        return 'es'
    if raw.startswith('en'):
        return 'en'
    return 'pt-BR'


def _api_t(key: str, lang: Optional[str] = None, **params) -> str:
    active_lang = lang or _get_request_lang()
    catalog = API_TRANSLATIONS.get(active_lang, API_TRANSLATIONS['pt-BR'])
    template = catalog.get(key) or API_TRANSLATIONS['pt-BR'].get(key) or key
    return template.format(**params)


def _json_response(payload: dict, status_code: int = 200, no_store: bool = False):
    response = jsonify(payload)
    response.status_code = status_code
    if no_store:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


def _internal_error_response(log_message: str, exc: Exception, *, no_store: bool = False):
    incident = datetime.now().strftime('%Y%m%d%H%M%S%f')[-10:]
    logger.exception("%s [incident=%s]", log_message, incident)
    return _json_response(
        {'success': False, 'error': _api_t('common.internal_error', incident=incident)},
        500,
        no_store=no_store,
    )


def _resolve_path_safe(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except (RuntimeError, OSError, ValueError) as exc:
        raise ValueError("invalid path") from exc


def _safe_child_path(root: Path, leaf_name: str) -> Optional[Path]:
    if not leaf_name or Path(leaf_name).name != leaf_name:
        return None
    try:
        root_resolved = _resolve_path_safe(root)
        candidate = _resolve_path_safe(root_resolved / leaf_name)
        candidate.relative_to(root_resolved)
        return candidate
    except (ValueError, RuntimeError, OSError):
        return None


def _normalize_scan_target_input(raw_path: str) -> str:
    candidate = (raw_path or '').strip()
    if not candidate:
        raise ValueError("missing target")

    if os.name == 'nt':
        normalized = candidate.replace('/', '\\')
        if re.fullmatch(r'\\\\\.\\PHYSICALDRIVE\d+', normalized, re.IGNORECASE):
            return normalized.upper()
        if re.fullmatch(r'[A-Za-z]:\\?', normalized):
            return normalized[:2].upper()

    path_obj = Path(candidate).expanduser()
    if not path_obj.is_absolute():
        raise ValueError("scan target must be absolute")
    resolved = _resolve_path_safe(path_obj)
    if os.name == 'nt' and str(resolved).startswith('\\\\'):
        raise ValueError("unc path not allowed")
    return str(resolved)


def _normalize_output_dir_input(raw_path: str) -> Path:
    path_obj = Path(raw_path).expanduser()
    if not path_obj.is_absolute():
        raise ValueError("output dir must be absolute")
    resolved = _resolve_path_safe(path_obj)
    if os.name == 'nt' and str(resolved).startswith('\\\\'):
        raise ValueError("unc path not allowed")
    return resolved


def _reset_progress() -> None:
    global scan_progress
    with _progress_lock:
        scan_progress = {**_PROGRESS_EMPTY}


def _extract_progress_metrics(message: str) -> Dict[str, int]:
    metrics: Dict[str, int] = {}
    for pattern in _FOUND_PATTERNS:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            metrics['files_found'] = int(match.group(1))
            break

    for category, patterns in _CATEGORY_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                metrics[category] = int(match.group(1))
                break

    return metrics


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        _resolve_path_safe(path).relative_to(_resolve_path_safe(root))
        return True
    except ValueError:
        return False


def _is_restricted_output_dir(path: Path) -> bool:
    resolved = _resolve_path_safe(path)

    if os.name == 'nt':
        if str(resolved).startswith('\\\\'):
            return True

        protected_roots = []
        for env_name in ('WINDIR', 'SYSTEMROOT', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA'):
            value = os.environ.get(env_name)
            if value:
                protected_roots.append(Path(value))

        system_root = os.environ.get('WINDIR') or os.environ.get('SYSTEMROOT')
        if system_root:
            protected_roots.append(Path(system_root) / 'System32')

        appdata = os.environ.get('APPDATA')
        if appdata:
            protected_roots.extend([
                Path(appdata) / 'Microsoft',
                Path(appdata) / 'Programs',
            ])

        localappdata = os.environ.get('LOCALAPPDATA')
        if localappdata:
            protected_roots.extend([
                Path(localappdata) / 'Microsoft',
                Path(localappdata) / 'Packages',
            ])

        return any(_path_is_within(resolved, root) for root in protected_roots)

    return (
        str(resolved) == '/'
        or any(_path_is_within(resolved, Path(root)) for root in ('/etc', '/bin', '/usr', '/var', '/boot', '/root'))
    )


def progress_callback(current: int, total: int, message: str) -> None:
    """Atualiza estado de progresso de forma thread-safe."""
    global scan_progress
    metrics = _extract_progress_metrics(message)
    with _progress_lock:
        scan_progress['current'] = current
        scan_progress['total']   = total
        scan_progress['message'] = message
        if 'files_found' in metrics:
            scan_progress['files_found'] = metrics['files_found']
        for cat in ('image', 'video', 'audio', 'document', 'archive'):
            if cat in metrics:
                scan_progress['file_counts'][cat] = metrics[cat]
    logger.debug("Progresso: %d/%d — %s", current, total, message)


def status_callback(status: RecoveryStatus, message: str) -> None:
    """Atualiza status de forma thread-safe."""
    with _progress_lock:
        scan_progress['status'] = status.value
    logger.info("Status: %s — %s", status.value, message)


# ── Rota principal ─────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


# ── API: Drives ────────────────────────────────────────────────────────────────
@app.route('/api/drives')
def get_drives():
    """Lista drives disponíveis no sistema."""
    try:
        drives = recovery_manager.get_drives() if recovery_manager else []
        return jsonify({'success': True, 'drives': drives})
    except Exception as exc:
        return _internal_error_response("Erro ao listar drives", exc)


# ── API: Tipos de arquivo ──────────────────────────────────────────────────────
@app.route('/api/file-types')
def get_file_types():
    """Retorna tipos de arquivo suportados, agrupados por categoria."""
    try:
        types      = recovery_manager.get_supported_file_types() if recovery_manager else []
        categories: Dict[str, list] = {}
        for ft in types:
            categories.setdefault(ft['category'], []).append(ft)
        return jsonify({'success': True, 'categories': categories, 'total': len(types)})
    except Exception as exc:
        return _internal_error_response("Erro ao obter tipos de arquivo", exc)


# ── API: SMART ─────────────────────────────────────────────────────────────────
@app.route('/api/smart')
def get_smart_info():
    """Retorna resumo SMART de todos os drives, com cache TTL de 60 s."""
    try:
        now = time.monotonic()
        if _smart_cache_state['data'] is not None and (now - _smart_cache_state['time']) < _SMART_CACHE_TTL_SECS:
            return jsonify({'success': True, 'available': True, 'data': _smart_cache_state['data'],
                            'cached': True})

        if smart_monitor and smart_monitor.is_available():
            summary = smart_monitor.get_health_summary()
            _smart_cache_state['data'] = summary
            _smart_cache_state['time'] = now
            return jsonify({'success': True, 'available': True, 'data': summary})
        else:
            return jsonify({
                'success': True, 'available': False,
                'message': _api_t('smart.unavailable'),
            })
    except Exception as exc:
        return _internal_error_response("Erro ao obter informações SMART", exc)


@app.route('/api/smart/refresh', methods=['POST'])
def refresh_smart():
    """Invalida o cache SMART e força nova leitura."""
    _smart_cache_state['data'] = None
    _smart_cache_state['time'] = 0.0
    return jsonify({'success': True, 'message': _api_t('smart.cache_cleared')})


@app.route('/api/smart/<device>')
def get_smart_device(device: str):
    """Retorna informações SMART de um dispositivo específico."""
    try:
        if not (smart_monitor and smart_monitor.is_available()):
            return jsonify({'success': False, 'error': _api_t('smart.unavailable_short')}), 503

        device_path = device.replace('|', '/')

        # Sanitização estrita: previne path traversal e injeção de argumentos
        if not re.match(
            r'^(?:[A-Za-z]:\\|/dev/[\w/]+|\\\\\\.\\PHYSICALDRIVE\d+)$',
            device_path, re.IGNORECASE,
        ):
            logger.warning("Caminho de dispositivo rejeitado: %s", device_path)
            return jsonify({'success': False, 'error': _api_t('smart.invalid_device_path')}), 400

        info = smart_monitor.get_smart_info(device_path)
        if info:
            return jsonify({'success': True, 'data': info.to_dict()})
        return jsonify({'success': False, 'error': _api_t('smart.info_unavailable')}), 404

    except Exception as exc:
        return _internal_error_response(f"Erro ao obter SMART do dispositivo {device}", exc)


# ── API: Varredura ─────────────────────────────────────────────────────────────
@app.route('/api/scan/start', methods=['POST'])
def start_scan():
    """Inicia varredura de disco em uma thread dedicada."""
    try:
        data       = request.get_json(force=True, silent=True) or {}
        drive_path = (data.get('drive') or '').strip()
        requested_mode = data.get('mode', 'quick')
        file_types = data.get('file_types') or None
        scan_lang  = _get_request_lang()
        scan_job_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        if not drive_path:
            return _json_response({'success': False, 'error': _api_t('scan.drive_missing', lang=scan_lang)}, 400, no_store=True)
        try:
            drive_path = _normalize_scan_target_input(drive_path)
        except ValueError:
            return _json_response({'success': False, 'error': _api_t('scan.invalid_target', lang=scan_lang)}, 400, no_store=True)

        if not recovery_manager:
            return _json_response({'success': False, 'error': _api_t('scan.system_unavailable', lang=scan_lang)}, 503, no_store=True)

        # Reseta progresso
        _reset_progress()
        with _progress_lock:
            scan_progress['status']  = 'scanning'
            scan_progress['message'] = _api_t('scan.starting', lang=scan_lang)
            scan_progress['total']   = 100
            scan_progress['job_id']  = scan_job_id

        # Limpa apenas o job ativo em memória para que o novo scan não herde
        # resultados antigos. O ponteiro persistido em disco é preservado aqui
        # para auditoria e só é removido num reset explícito do usuário.
        recovery_manager.reset_current_job(clear_persisted_state=False)

        recovery_manager.set_callbacks(progress_callback, status_callback)

        def _do_scan():
            try:
                scan_mode = ScanMode.QUICK if requested_mode == 'quick' else ScanMode.DEEP
                job = recovery_manager.start_scan_only(drive_path, scan_mode, file_types, job_id=scan_job_id)
                n   = len(job.scan_results)
                with _progress_lock:
                    completed_units = scan_progress['total']
                    if completed_units <= 0:
                        completed_units = scan_progress['current']
                    scan_progress['status']      = 'completed'
                    scan_progress['message']     = _api_t('scan.completed', lang=scan_lang, count=n)
                    scan_progress['files_found'] = n
                    scan_progress['current']     = completed_units
                    scan_progress['total']       = completed_units
                logger.info("Varredura concluída: %d arquivo(s).", n)
            except Exception as exc:
                logger.error("Erro na varredura: %s", exc)
                with _progress_lock:
                    scan_progress['status']  = 'error'
                    scan_progress['message'] = _api_t('common.error_with_message', lang=scan_lang, message=exc)

        t = threading.Thread(target=_do_scan, name='revivax-scan', daemon=True)
        t.start()

        scan_context = recovery_manager.get_scan_target_context(
            drive_path,
            ScanMode.QUICK if requested_mode == 'quick' else ScanMode.DEEP,
        )
        return _json_response({
            'success': True,
            'message': _api_t('scan.started', lang=scan_lang),
            'job_id': scan_job_id,
            'requested_mode': requested_mode,
            'effective_mode': scan_context.get('effective_mode'),
            'source_kind': scan_context.get('source_kind'),
            'filesystem': scan_context.get('filesystem'),
            'supports_deep_folder_scan': scan_context.get('supports_deep_folder_scan'),
            'scan_strategy': scan_context.get('strategy'),
            'scan_note_code': scan_context.get('note_code'),
        }, no_store=True)

    except Exception as exc:
        return _internal_error_response("Erro ao iniciar varredura", exc, no_store=True)


@app.route('/api/scan/progress')
def get_scan_progress():
    """Retorna progresso atual da varredura."""
    with _progress_lock:
        snapshot = {**scan_progress, 'file_counts': dict(scan_progress.get('file_counts', {}))}
    return _json_response({'success': True, 'progress': snapshot}, no_store=True)


@app.route('/api/scan/reset', methods=['POST'])
def reset_scan():
    """Limpa o estado da última varredura para iniciar um novo ciclo limpo."""
    try:
        if recovery_manager:
            job = recovery_manager.get_current_job()
            if job and job.status in (RecoveryStatus.SCANNING, RecoveryStatus.PAUSED, RecoveryStatus.CARVING):
                recovery_manager.stop()
            recovery_manager.reset_current_job(clear_persisted_state=True)
        _reset_progress()
        return _json_response({'success': True}, no_store=True)
    except Exception as exc:
        return _internal_error_response("Erro ao limpar estado da varredura", exc, no_store=True)


@app.route('/api/scan/progress/stream')
def get_scan_progress_stream():
    """Streaming de eventos Server-Sent Events (SSE) do progresso."""
    expected_job_id = (request.args.get('job_id') or '').strip()

    def generate():
        while True:
            with _progress_lock:
                snapshot = {**scan_progress, 'file_counts': dict(scan_progress.get('file_counts', {}))}

            if expected_job_id and snapshot.get('job_id') and snapshot.get('job_id') != expected_job_id:
                break
            
            data = json.dumps({'success': True, 'progress': snapshot})
            yield f"data: {data}\n\n"
            
            # Interrompe o stream quando finalizado
            if snapshot.get('status') in ('completed', 'error', 'stopped', 'paused'):
                break
            
            # Rate limit de 500ms por frame para SSE
            time.sleep(0.5)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0',
            'X-Accel-Buffering': 'no',
        },
    )


@app.route('/api/scan/results')
def get_scan_results():
    """Retorna lista de arquivos encontrados na última varredura."""
    try:
        expected_job_id = (request.args.get('job_id') or '').strip()
        job = recovery_manager.get_current_job() if recovery_manager else None
        if expected_job_id and (not job or job.id != expected_job_id):
            return _json_response({
                'success': True,
                'results': [],
                'total': 0,
                'job_id': expected_job_id,
                'pending': True,
            }, no_store=True)

        if not job or not job.scan_results:
            return _json_response({'success': True, 'results': [], 'total': 0, 'job_id': expected_job_id or None}, no_store=True)

        results = []
        for r in job.scan_results:
            results.append({
                'offset':            r.offset,
                'size':              r.size,
                'size_formatted':    _fmt_bytes(r.size),
                'file_type':         r.file_type,
                'extension':         r.extension,
                'category':          get_extension_category(r.extension),
                'confidence':        r.confidence,
                'confidence_percent': int(r.confidence * 100),
                'signature_matched': r.signature_matched,
                'is_fragmented':     r.is_fragmented,
            })
        results.sort(key=lambda x: x['confidence'], reverse=True)

        scan_context = (job.stats or {}).get('scan_context') or recovery_manager.get_scan_target_context(job.drive_path, job.mode)

        return _json_response({
            'success': True,
            'results': results,
            'total':   len(results),
            'job_id':  job.id,
            'drive':   job.drive_path,
            'mode':    job.mode.value,
            'source_kind': recovery_manager.get_scan_source_kind(job.drive_path),
            'scan_context': scan_context,
            'created_at': job.created_at.isoformat(),
        }, no_store=True)
    except Exception as exc:
        return _internal_error_response("Erro ao obter resultados de varredura", exc, no_store=True)


@app.route('/api/scan/stop', methods=['POST'])
def stop_scan():
    """Interrompe a varredura em andamento."""
    try:
        if recovery_manager:
            recovery_manager.stop()
        with _progress_lock:
            scan_progress['status']  = 'stopped'
            scan_progress['message'] = _api_t('scan.stopped_by_user')
        return jsonify({'success': True, 'message': _api_t('scan.stopped')})
    except Exception as exc:
        return _internal_error_response("Erro ao interromper varredura", exc)


@app.route('/api/scan/pause', methods=['POST'])
def pause_scan():
    """Pausa a varredura em andamento."""
    try:
        if recovery_manager:
            recovery_manager.pause()
        with _progress_lock:
            scan_progress['status'] = 'paused'
        return jsonify({'success': True, 'message': _api_t('scan.paused')})
    except Exception as exc:
        return _internal_error_response("Erro ao pausar varredura", exc)


@app.route('/api/scan/resume', methods=['POST'])
def resume_scan():
    """Retoma a varredura pausada."""
    try:
        if recovery_manager:
            recovery_manager.resume()
        with _progress_lock:
            scan_progress['status'] = 'scanning'
        return jsonify({'success': True, 'message': _api_t('scan.resumed')})
    except Exception as exc:
        return _internal_error_response("Erro ao retomar varredura", exc)


# ── API: Recuperação ───────────────────────────────────────────────────────────
@app.route('/api/recover/start', methods=['POST'])
def start_recovery():
    """Inicia recuperação dos arquivos selecionados."""
    try:
        data       = request.get_json(force=True, silent=True) or {}
        indices    = data.get('indices', [])
        output_dir = data.get('output_dir')
        recover_lang = _get_request_lang()

        job = recovery_manager.get_current_job() if recovery_manager else None
        if not job or not job.scan_results:
            return jsonify({'success': False, 'error': _api_t('recover.no_scan_results', lang=recover_lang)}), 400

        # Valida índices
        valid_indices = [i for i in indices if isinstance(i, int) and 0 <= i < len(job.scan_results)]
        selected = [job.scan_results[i] for i in valid_indices] if valid_indices \
                   else [r for r in job.scan_results if r.confidence >= 0.5]

        if not selected:
            return jsonify({'success': False, 'error': _api_t('recover.no_selection', lang=recover_lang)}), 400

        job.carve_results = []
        job.status = RecoveryStatus.CARVING
        job.updated_at = datetime.now()

        if output_dir:
            try:
                out = _normalize_output_dir_input(output_dir)
            except ValueError:
                return jsonify({'success': False, 'error': _api_t('recover.invalid_output_dir', lang=recover_lang)}), 400

            if _is_restricted_output_dir(out):
                error_key = 'recover.protected_output_dir' if os.name == 'nt' else 'recover.restricted_output_dir'
                return jsonify({'success': False, 'error': _api_t(error_key, lang=recover_lang)}), 403
                    
            out.mkdir(parents=True, exist_ok=True)
            recovery_manager.carver.output_dir = out

        def _do_recovery():
            try:
                results = recovery_manager.carve_selected(job.drive_path, selected)
                job.carve_results = results
                n = len([r for r in results if r.success])
                logger.info("Recuperação concluída: %d arquivo(s) recuperado(s).", n)
            except Exception as exc:
                logger.error("Erro FATAL na thread de recuperação: %s", exc)
                # Fallback STAB-01: Evita hangs do front-end forçando resultados de erro
                job.carve_results = [
                    CarveResult(
                        success=False,
                        source_offset=s.offset,
                        recovered_path=None,
                        original_size=s.size,
                        recovered_size=0,
                        hash_md5=None,
                        hash_sha256=None,
                        error_message=_api_t('recover.internal_failure', lang=recover_lang, message=exc)
                    ) for s in selected
                ]

        threading.Thread(target=_do_recovery, name='revivax-recovery', daemon=True).start()
        return jsonify({'success': True, 'message': _api_t('recover.started', lang=recover_lang, count=len(selected))})

    except Exception as exc:
        return _internal_error_response("Erro ao iniciar recuperação", exc)


@app.route('/api/recover/results')
def get_recovery_results():
    """Retorna resultados da última operação de recuperação."""
    try:
        job = recovery_manager.get_current_job() if recovery_manager else None
        if job and job.status == RecoveryStatus.CARVING:
            return jsonify({'success': True, 'results': [], 'total': 0, 'successful': 0, 'pending': True})
        if not job or not job.carve_results:
            return jsonify({'success': True, 'results': [], 'total': 0, 'successful': 0})

        results = [{
            'success':                  r.success,
            'source_offset':            r.source_offset,
            'recovered_path':           r.recovered_path,
            'original_size':            r.original_size,
            'original_size_formatted':  _fmt_bytes(r.original_size),
            'recovered_size':           r.recovered_size,
            'recovered_size_formatted': _fmt_bytes(r.recovered_size),
            'hash_md5':                 r.hash_md5,
            'hash_sha256':              r.hash_sha256,
            'verification_status':      r.verification_status,
            'error_message':            r.error_message,
        } for r in job.carve_results]

        return jsonify({
            'success':    True,
            'results':    results,
            'total':      len(results),
            'successful': sum(1 for r in results if r['success']),
        })
    except Exception as exc:
        return _internal_error_response("Erro ao obter resultados de recuperação", exc)


# ── API: Estimativa ────────────────────────────────────────────────────────────
@app.route('/api/estimate', methods=['POST'])
def get_recovery_estimate():
    """Calcula estimativa de recuperabilidade para um drive."""
    try:
        data       = request.get_json(force=True, silent=True) or {}
        drive_path = (data.get('drive') or '').strip()
        if not drive_path:
            return jsonify({'success': False, 'error': _api_t('estimate.drive_missing')}), 400
        try:
            drive_path = _normalize_scan_target_input(drive_path)
        except ValueError:
            return jsonify({'success': False, 'error': _api_t('scan.invalid_target')}), 400
        estimate = recovery_manager.get_recovery_estimate(drive_path) if recovery_manager else {}
        return jsonify({'success': True, 'estimate': estimate})
    except Exception as exc:
        return _internal_error_response("Erro ao calcular estimativa", exc)


# ── API: Logs ──────────────────────────────────────────────────────────────────
@app.route('/api/logs')
def get_logs():
    """Retorna conteúdo dos logs recentes (últimos 5 arquivos, últimos 5 KB cada)."""
    try:
        logs_dir = recovery_manager.logs_dir if recovery_manager else get_logs_dir()
        logs     = []
        if logs_dir.exists():
            for log_file in sorted(logs_dir.glob('*.log'), reverse=True)[:5]:
                try:
                    content = log_file.read_text(encoding='utf-8', errors='replace')
                    logs.append({
                        'filename': log_file.name,
                        'content':  content[-5000:] if len(content) > 5000 else content,
                    })
                except OSError as exc:
                    logger.debug("Falha ao ler log %s: %s", log_file.name, exc)
        return jsonify({'success': True, 'logs': logs})
    except Exception as exc:
        return _internal_error_response("Erro ao ler logs", exc)


@app.route('/api/logs/delete', methods=['POST'])
def delete_log():
    """Exclui um arquivo de log específico."""
    try:
        data     = request.get_json(force=True, silent=True) or {}
        filename = (data.get('filename') or '').strip()
        logs_dir = recovery_manager.logs_dir if recovery_manager else get_logs_dir()
        log_path = _safe_child_path(logs_dir, filename)
        if log_path is None:
            return jsonify({'success': False, 'error': _api_t('logs.invalid_filename')}), 400
        if not log_path.exists() or not log_path.is_file():
            return jsonify({'success': False, 'error': _api_t('logs.not_found')}), 404
        log_path.unlink()
        logger.info("Log excluído: %s", filename)
        return jsonify({'success': True})
    except Exception as exc:
        return _internal_error_response("Erro ao excluir log", exc)


@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    """Exclui todos os arquivos de log (.log e .json de export)."""
    try:
        logs_dir = recovery_manager.logs_dir if recovery_manager else get_logs_dir()
        deleted  = 0
        if logs_dir.exists():
            for f in logs_dir.glob('*'):
                if f.suffix in ('.log', '.json', '.csv') and f.is_file():
                    try:
                        # Trunca log existente para não violar locks em arquivos abertos (WinError 32)
                        if f.suffix == '.log':
                            with open(f, 'w', encoding='utf-8'):
                                pass
                        else:
                            f.unlink()
                        deleted += 1
                    except Exception as e:
                        logger.warning("Falha ao limpar %s: %s", f.name, e)
        logger.info("Logs limpos: %d arquivo(s) removido(s).", deleted)
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as exc:
        return _internal_error_response("Erro ao limpar logs", exc)


# ── API: Exportação ────────────────────────────────────────────────────────────
@app.route('/api/export/results', methods=['POST'])
def export_results():
    """Exporta resultados da varredura em JSON ou CSV."""
    try:
        data        = request.get_json(force=True, silent=True) or {}
        fmt         = data.get('format', 'json').lower()
        job         = recovery_manager.get_current_job() if recovery_manager else None

        if not job:
            return jsonify({'success': False, 'error': _api_t('export.no_scan')}), 400

        export_dir = recovery_manager.logs_dir if recovery_manager else get_logs_dir()
        export_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')

        if fmt == 'json':
            filename = f'export_{ts}.json'
            filepath = export_dir / filename
            payload  = {
                'job_id':  job.id, 'drive': job.drive_path, 'mode': job.mode.value,
                'scan_results': [
                    {'offset': r.offset, 'size': r.size, 'type': r.file_type,
                     'extension': r.extension, 'confidence': r.confidence}
                    for r in job.scan_results
                ],
            }
            filepath.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')

        elif fmt == 'csv':
            filename = f'export_{ts}.csv'
            filepath = export_dir / filename
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow([
                    _api_t('export.csv.offset'),
                    _api_t('export.csv.size'),
                    _api_t('export.csv.type'),
                    _api_t('export.csv.extension'),
                    _api_t('export.csv.confidence'),
                ])
                for r in job.scan_results:
                    w.writerow([r.offset, r.size, r.file_type, r.extension, f'{r.confidence:.2f}'])
        else:
            return jsonify({'success': False, 'error': _api_t('export.unsupported_format', format=fmt)}), 400

        return jsonify({'success': True, 'filename': filename, 'download_url': f'/api/download/{filename}'})

    except Exception as exc:
        return _internal_error_response("Erro ao exportar resultados", exc)


@app.route('/api/browse-folder', methods=['POST'])
def browse_folder():
    """
    Abre o seletor de pasta nativo do Windows via PowerShell e retorna o caminho selecionado.
    Funciona apenas em modo local (localhost).
    """
    try:
        if os.name != 'nt':
            return jsonify({'success': False, 'error': _api_t('browse.windows_only')}), 400

        browse_title = _api_t('browse.dialog_title')
        
        # Script usa tkinter que é mais robusto e não dá timeout no Waitress como o Forms via PS
        tk_script = (
            "import os, tkinter as tk, tkinter.filedialog as fd; "
            "r = tk.Tk(); "
            "r.attributes('-topmost', 1); "
            "r.withdraw(); "
            "title = os.environ.get('REVIVAX_BROWSE_TITLE', 'Select the folder to scan'); "
            "path = fd.askdirectory(title=title); "
            "r.update(); "
            "r.destroy(); "
            "print(path if path else '')"
        )
        
        child_env = os.environ.copy()
        child_env['REVIVAX_BROWSE_TITLE'] = browse_title
        out = sp.check_output(
            [sys.executable, '-c', tk_script],
            text=True,
            timeout=120,
            env=child_env,
        ).strip()

        if out:
            return jsonify({'success': True, 'path': out})
        else:
            return jsonify({'success': False, 'cancelled': True})
    except Exception as exc:
        return _internal_error_response("Erro ao abrir seletor de pasta", exc)


@app.route('/api/download/<filename>')
def download_file(filename: str):
    """Faz download de um arquivo exportado."""
    try:
        # Sanitização: apenas nome de arquivo, sem diretórios
        logs_dir = recovery_manager.logs_dir if recovery_manager else get_logs_dir()
        filepath = _safe_child_path(logs_dir, filename)
        if filepath is None:
            return jsonify({'success': False, 'error': _api_t('download.invalid_filename')}), 400
        if not filepath.exists() or not filepath.is_file():
            return jsonify({'success': False, 'error': _api_t('download.not_found')}), 404
        return send_file(filepath, as_attachment=True)
    except Exception as exc:
        return _internal_error_response("Erro no download de arquivo", exc)


# ── Utilitários ────────────────────────────────────────────────────────────────
def _fmt_bytes(b: int) -> str:
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if b < 1024:
            return f'{b:.2f} {u}'
        b /= 1024
    return f'{b:.2f} PB'


@app.after_request
def _apply_security_headers(response):
    response.headers.setdefault('Content-Security-Policy', _CSP_POLICY)
    response.headers.setdefault('Referrer-Policy', 'no-referrer')
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
    return response


# ── Inicialização lazy ─────────────────────────────────────────────────────────
@app.before_request
def _ensure_managers():
    """Garante que os gerenciadores estejam inicializados antes da primeira requisição."""
    global recovery_manager, smart_monitor
    if recovery_manager is None:
        init_managers()


# ── Execução direta (desenvolvimento) ─────────────────────────────────────────
if __name__ == '__main__':
    init_managers()
    print('=' * 60)
    print('  RevivaX — Sistema de Recuperação de Arquivos')
    print('  Acesse: http://127.0.0.1:5000')
    print('  Pressione Ctrl+C para encerrar')
    print('=' * 60)
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
