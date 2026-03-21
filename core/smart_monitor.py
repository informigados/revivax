"""
RevivaX - SMART Monitor Module
Módulo de monitoramento de saúde de discos via SMART
"""

import os
import re
import logging
import subprocess
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class SMARTStatus(Enum):
    """Status de saúde do disco"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass
class SMARTAttribute:
    """Atributo SMART individual"""
    id: int
    name: str
    value: int
    worst: int
    threshold: int
    raw_value: int
    status: str
    flags: str = ""
    
    @property
    def is_critical(self) -> bool:
        """Verifica se atributo está em estado crítico"""
        return self.value <= self.threshold and self.threshold != 0
    
    @property
    def is_warning(self) -> bool:
        """Verifica se atributo está em alerta"""
        if self.name in ['Reallocated_Sector_Ct', 'Current_Pending_Sector']:
            return self.raw_value > 0
        elif self.name in ['Temperature_Celsius']:
            return self.raw_value > 50
        return False


@dataclass
class SMARTInfo:
    """Informações SMART completas do disco"""
    device: str
    model: str
    serial: str
    firmware: str
    capacity: int
    sector_size: int
    rotation_rate: Optional[int]
    is_ssd: bool
    smart_enabled: bool
    overall_status: SMARTStatus
    temperature: Optional[int]
    power_on_hours: Optional[int]
    power_cycle_count: Optional[int]
    unsafe_shutdowns: Optional[int] = None
    media_errors: Optional[int] = None
    error_log_entries: Optional[int] = None
    available_spare: Optional[int] = None
    percentage_used: Optional[int] = None
    attributes: List[SMARTAttribute] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    self_tests: List[Dict] = field(default_factory=list)
    estimated_life: Optional[int] = None  # Percentual estimado de vida útil
    
    def to_dict(self) -> Dict:
        """Converte para dicionário"""
        return {
            'device': self.device,
            'model': self.model,
            'serial': self.serial,
            'firmware': self.firmware,
            'capacity': self.capacity,
            'capacity_formatted': self._format_bytes(self.capacity),
            'sector_size': self.sector_size,
            'rotation_rate': self.rotation_rate,
            'is_ssd': self.is_ssd,
            'smart_enabled': self.smart_enabled,
            'overall_status': self.overall_status.value,
            'temperature': self.temperature,
            'power_on_hours': self.power_on_hours,
            'power_on_hours_formatted': self._format_hours(self.power_on_hours) if self.power_on_hours else None,
            'power_cycle_count': self.power_cycle_count,
            'unsafe_shutdowns': self.unsafe_shutdowns,
            'media_errors': self.media_errors,
            'error_log_entries': self.error_log_entries,
            'available_spare': self.available_spare,
            'percentage_used': self.percentage_used,
            'estimated_life_percent': self.estimated_life,
            'attributes': [
                {
                    'id': a.id,
                    'name': a.name,
                    'value': a.value,
                    'worst': a.worst,
                    'threshold': a.threshold,
                    'raw_value': a.raw_value,
                    'status': a.status,
                    'is_critical': a.is_critical,
                    'is_warning': a.is_warning
                }
                for a in self.attributes
            ],
            'errors': self.errors,
            'self_tests': self.self_tests
        }
    
    def _format_bytes(self, bytes_val: int) -> str:
        """Formata bytes para string legível"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
            if bytes_val < 1024:
                return f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.2f} EB"
    
    def _format_hours(self, hours: int) -> str:
        """Formata horas para string legível"""
        days = hours // 24
        remaining_hours = hours % 24
        years = days // 365
        remaining_days = days % 365
        
        if years > 0:
            return f"{years}a {remaining_days}d {remaining_hours}h"
        elif days > 0:
            return f"{days}d {remaining_hours}h"
        else:
            return f"{hours}h"


class SMARTMonitor:
    """
    Monitor de saúde de discos via SMART
    """
    
    # Atributos críticos a monitorar
    CRITICAL_ATTRIBUTES = [
        'Reallocated_Sector_Ct',
        'Current_Pending_Sector',
        'Offline_Uncorrectable',
        'UDMA_CRC_Error_Count',
        'Multi_Zone_Error_Rate',
        'Seek_Error_Rate',
    ]
    
    # Atributos de temperatura
    TEMP_ATTRIBUTES = [
        'Temperature_Celsius',
        'Airflow_Temperature_Cel',
    ]
    
    # Atributos de desgaste SSD
    SSD_WEAR_ATTRIBUTES = [
        'Wear_Leveling_Count',
        'Percent_Lifetime_Remain',
        'Media_Wearout_Indicator',
        'SSD_Life_Left',
    ]
    
    def __init__(self):
        self.smartctl_path = self._find_smartctl()
        self._cache: Dict[str, Tuple[SMARTInfo, datetime]] = {}
        self._cache_ttl = 60  # segundos
    
    def _find_smartctl(self) -> Optional[str]:
        """
        Localiza o smartctl disponível, priorizando:
        1. tools/smartctl.exe  (portátil local, já baixado)
        2. PATH do sistema     (instalação manual)
        3. Program Files       (instalador padrão Windows)
        4. Download automático do GitHub Releases (primeira execução)
        """
        try:
            from core.smartctl_setup import ensure_smartctl
            path = ensure_smartctl()
            if path:
                return path
        except Exception as exc:
            logger.debug("ensure_smartctl falhou: %s — tentando fallback.", exc)

        # Fallback Linux / macOS (sem download automático)
        if os.name != 'nt':
            import shutil
            for candidate in ('/usr/sbin/smartctl', '/usr/bin/smartctl',
                              '/sbin/smartctl', 'smartctl'):
                if shutil.which(candidate) or self._command_exists(candidate):
                    return candidate

        logger.warning(
            "smartctl não encontrado. SMART usará apenas PowerShell (Windows). "
            "Para dados completos, instale o smartmontools: https://www.smartmontools.org/"
        )
        return None
    
    def _command_exists(self, cmd: str) -> bool:
        """Verifica se comando existe"""
        try:
            subprocess.run([cmd, '--version'], 
                         capture_output=True, 
                         check=False,
                         timeout=5)
            return True
        except Exception:
            return False
    
    def is_available(self) -> bool:
        """Verifica se SMART está disponível (via smartctl ou fallback nativo WMI do Windows)"""
        return self.smartctl_path is not None or os.name == 'nt'
    
    def scan_drives(self) -> List[Dict]:
        """
        Escaneia discos disponíveis no sistema
        
        Returns:
            Lista de discos encontrados
        """
        if not self.is_available():
            logger.error("smartctl não disponível")
            return []
        
        drives = []
        
        try:
            # Executa smartctl --scan
            result = subprocess.run(
                [self.smartctl_path, '--scan'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"smartctl scan error: {result.stderr}")
                return []
            
            # Parse da saída
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                parts = line.split()
                if parts:
                    device = parts[0]
                    drive_type = parts[1] if len(parts) > 1 else 'auto'
                    
                    drives.append({
                        'device': device,
                        'type': drive_type,
                        'name': os.path.basename(device)
                    })
            
            # Windows: também tenta listar drives físicos
            if os.name == 'nt' and not drives:
                drives = self._scan_windows_drives()
            
        except Exception as e:
            logger.error(f"Erro ao escanear drives: {e}")
        
        return drives
    
    def _scan_windows_drives(self) -> List[Dict]:
        """Escaneia drives no Windows"""
        drives = []
        
        try:
            # Lista discos físicos com WMIC
            result = subprocess.run(
                ['wmic', 'diskdrive', 'get', 'DeviceID,Model,Size', '/format:csv'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            for line in result.stdout.split('\n'):
                if r'\\.\PHYSICALDRIVE' in line or r'\.\PHYSICALDRIVE' in line:
                    parts = line.strip().split(',')
                    if len(parts) >= 3:
                        device_id = parts[1].strip()
                        model = parts[2].strip() if len(parts) > 2 else 'Unknown'
                        
                        drives.append({
                            'device': f'\\\\.\\{device_id}',
                            'type': 'auto',
                            'name': device_id,
                            'model': model
                        })
        
        except Exception as e:
            logger.error(f"Erro ao escanear drives Windows: {e}")
        
        return drives
    
    def get_smart_info(self, device: str, use_cache: bool = True) -> Optional[SMARTInfo]:
        """
        Obtém informações SMART de um disco
        
        Args:
            device: Caminho do dispositivo
            use_cache: Se deve usar cache
            
        Returns:
            SMARTInfo ou None
        """
        if not self.is_available():
            return None
        
        # Verifica cache
        if use_cache and device in self._cache:
            info, timestamp = self._cache[device]
            if (datetime.now() - timestamp).seconds < self._cache_ttl:
                return info
        
        try:
            # Executa smartctl -a
            result = subprocess.run(
                [self.smartctl_path, '-a', device],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            has_parseable_output = '=== START OF INFORMATION SECTION ===' in (result.stdout or '')
            if result.returncode not in [0, 4, 8, 16, 32, 64, 128, 192] and not has_parseable_output:
                logger.error(f"smartctl error on {device}: {result.stderr}")
                return None
            
            info = self._parse_smart_output(result.stdout, device)
            
            # Atualiza cache
            self._cache[device] = (info, datetime.now())
            
            return info
            
        except Exception as e:
            logger.error(f"Erro ao obter SMART de {device}: {e}")
            return None
    
    def _parse_smart_output(self, output: str, device: str) -> SMARTInfo:
        """Parse da saída do smartctl"""
        info = SMARTInfo(
            device=device,
            model='Unknown',
            serial='Unknown',
            firmware='Unknown',
            capacity=0,
            sector_size=512,
            rotation_rate=None,
            is_ssd=False,
            smart_enabled=False,
            overall_status=SMARTStatus.UNKNOWN,
            temperature=None,
            power_on_hours=None,
            power_cycle_count=None
        )
        
        lines = output.split('\n')
        in_attributes = False
        
        for line in lines:
            line = line.strip()
            
            # Informações do modelo
            if line.startswith('Device Model:'):
                info.model = line.split(':', 1)[1].strip()
            elif line.startswith('Model Number:'):
                info.model = line.split(':', 1)[1].strip()
            elif line.startswith('Serial Number:'):
                info.serial = line.split(':', 1)[1].strip()
            elif line.startswith('Firmware Version:'):
                info.firmware = line.split(':', 1)[1].strip()
            elif line.startswith('User Capacity:'):
                # Extrai capacidade
                match = re.search(r'\[(\d[\d\.,]*)\s*bytes\]', line)
                if match:
                    info.capacity = int(re.sub(r'\D', '', match.group(1)))
            elif line.startswith('Total NVM Capacity:'):
                match = re.search(r'(\d[\d\.,]*)', line)
                if match:
                    info.capacity = int(re.sub(r'\D', '', match.group(1)))
            elif line.startswith('Sector Size:'):
                match = re.search(r'(\d+)', line)
                if match:
                    info.sector_size = int(match.group(1))
            elif line.startswith('Namespace 1 Formatted LBA Size:'):
                match = re.search(r'(\d+)', line)
                if match:
                    info.sector_size = int(match.group(1))
            elif line.startswith('Rotation Rate:'):
                if 'Solid State' in line or 'SSD' in line:
                    info.is_ssd = True
                    info.rotation_rate = 0
                else:
                    match = re.search(r'(\d+)', line)
                    if match:
                        info.rotation_rate = int(match.group(1))
            elif line.startswith('NVMe Version:'):
                info.is_ssd = True
                info.rotation_rate = 0
            elif line.startswith('SMART support is:'):
                if 'Enabled' in line:
                    info.smart_enabled = True
            
            # Status geral
            elif 'SMART overall-health' in line:
                if 'PASSED' in line:
                    info.overall_status = SMARTStatus.HEALTHY
                elif 'FAILED' in line:
                    info.overall_status = SMARTStatus.CRITICAL
            elif line.startswith('Temperature:') and info.temperature is None:
                value = self._parse_raw_value(line.split(':', 1)[1])
                if value > 0:
                    info.temperature = value
            elif line.startswith('Power On Hours:') and info.power_on_hours is None:
                info.power_on_hours = self._parse_raw_value(line.split(':', 1)[1])
            elif line.startswith('Power Cycles:') and info.power_cycle_count is None:
                info.power_cycle_count = self._parse_raw_value(line.split(':', 1)[1])
            elif line.startswith('Unsafe Shutdowns:'):
                info.unsafe_shutdowns = self._parse_raw_value(line.split(':', 1)[1])
            elif line.startswith('Media and Data Integrity Errors:'):
                info.media_errors = self._parse_raw_value(line.split(':', 1)[1])
            elif line.startswith('Error Information Log Entries:'):
                info.error_log_entries = self._parse_raw_value(line.split(':', 1)[1])
            elif line.startswith('Percentage Used:'):
                used = self._parse_raw_value(line.split(':', 1)[1])
                info.percentage_used = used
                info.estimated_life = max(0, min(100, 100 - used))
            elif line.startswith('Available Spare:') and info.estimated_life is None:
                spare = self._parse_raw_value(line.split(':', 1)[1])
                info.available_spare = spare
                info.estimated_life = max(0, min(100, spare))
            elif line.startswith('Available Spare:'):
                info.available_spare = self._parse_raw_value(line.split(':', 1)[1])
            
            # Início da tabela de atributos
            elif 'ID# ATTRIBUTE_NAME' in line:
                in_attributes = True
                continue
            
            # Parse de atributos
            elif in_attributes and line and line[0].isdigit():
                attr = self._parse_attribute_line(line)
                if attr:
                    info.attributes.append(attr)
                    
                    # Extrai temperatura
                    if attr.name in self.TEMP_ATTRIBUTES and info.temperature is None:
                        info.temperature = attr.raw_value
                    
                    # Extrai horas de uso
                    if attr.name == 'Power_On_Hours':
                        info.power_on_hours = attr.raw_value
                    
                    # Extrai ciclos de energia
                    if attr.name == 'Power_Cycle_Count':
                        info.power_cycle_count = attr.raw_value
                    
                    # Calcula vida útil SSD
                    if info.is_ssd and attr.name in self.SSD_WEAR_ATTRIBUTES:
                        if attr.name == 'Percent_Lifetime_Remain':
                            info.estimated_life = attr.value
                        elif attr.name == 'Wear_Leveling_Count':
                            info.estimated_life = 100 - min(attr.raw_value, 100)
            
            # Fim da tabela
            elif in_attributes and not line:
                in_attributes = False
        
        # Atributos relevantes têm precedência sobre o PASSED/FAILED genérico do firmware.
        critical_count = sum(1 for a in info.attributes if a.is_critical)
        warning_count = sum(1 for a in info.attributes if a.is_warning)

        if critical_count > 0:
            info.overall_status = SMARTStatus.CRITICAL
        elif warning_count > 0 and info.overall_status != SMARTStatus.CRITICAL:
            info.overall_status = SMARTStatus.WARNING
        elif info.overall_status == SMARTStatus.UNKNOWN:
            info.overall_status = SMARTStatus.HEALTHY
        
        return info
    
    def _parse_attribute_line(self, line: str) -> Optional[SMARTAttribute]:
        """Parse de uma linha de atributo SMART"""
        try:
            # Formato: ID# ATTRIBUTE_NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE
            parts = line.split()
            if len(parts) >= 10:
                threshold = int(parts[5]) if parts[5].isdigit() else 0
                return SMARTAttribute(
                    id=int(parts[0]),
                    name=parts[1],
                    flags=parts[2],
                    value=int(parts[3]),
                    worst=int(parts[4]),
                    threshold=threshold,
                    status=' '.join(parts[6:9]),
                    raw_value=self._parse_raw_value(' '.join(parts[9:]))
                )
        except Exception as e:
            logger.debug(f"Erro ao parsear atributo: {line} - {e}")
        
        return None
    
    def _parse_raw_value(self, value_str: str) -> int:
        """Parse do valor raw (pode ter formato especial)"""
        try:
            cleaned = re.sub(r'(?<=\d)[\.,](?=\d)', '', value_str)
            match = re.search(r'(\d+)', cleaned)
            if match:
                return int(match.group(1))
        except (TypeError, ValueError) as exc:
            logger.debug("Falha ao interpretar valor SMART bruto %r: %s", value_str, exc)
        return 0

    @staticmethod
    def _normalize_key(value: Optional[str]) -> str:
        return re.sub(r'[^A-Z0-9]', '', (value or '').upper())

    def _get_windows_smartctl_map(self) -> Dict[str, SMARTInfo]:
        """Mapeia informações detalhadas do smartctl por serial/modelo no Windows."""
        if not self.smartctl_path:
            return {}

        details: Dict[str, SMARTInfo] = {}
        try:
            result = subprocess.run(
                [self.smartctl_path, '--scan-open'],
                capture_output=True,
                text=True,
                timeout=20
            )
            if result.returncode != 0:
                return {}

            devices = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if parts:
                    devices.append(parts[0])

            for dev in devices:
                info = self.get_smart_info(dev, use_cache=False)
                if not info:
                    continue

                serial_key = self._normalize_key(info.serial)
                model_key = self._normalize_key(info.model)
                if serial_key:
                    details[f'serial:{serial_key}'] = info
                if model_key and f'model:{model_key}' not in details:
                    details[f'model:{model_key}'] = info

        except Exception as exc:
            logger.debug("Falha ao mapear smartctl no Windows: %s", exc)

        return details
    
    def run_self_test(self, device: str, test_type: str = 'short') -> Dict:
        """
        Executa self-test no disco
        
        Args:
            device: Caminho do dispositivo
            test_type: 'short', 'long', ou 'conveyance'
            
        Returns:
            Dict com resultado
        """
        if not self.is_available():
            return {'success': False, 'error': 'smartctl não disponível'}
        
        try:
            result = subprocess.run(
                [self.smartctl_path, '-t', test_type, device],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            return {
                'success': result.returncode == 0,
                'output': result.stdout,
                'error': result.stderr if result.returncode != 0 else None,
                'test_type': test_type,
                'device': device
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_all_drives_info(self) -> List[Dict]:
        """
        Obtém informações SMART de todos os drives
        
        Returns:
            Lista de dicts com informações
        """
        drives = self.scan_drives()
        results = []
        
        for drive in drives:
            info = self.get_smart_info(drive['device'])
            if info:
                results.append(info.to_dict())
            else:
                results.append({
                    'device': drive['device'],
                    'error': 'Não foi possível obter informações SMART',
                    'overall_status': 'error'
                })
        
        return results
    
    def get_health_summary(self) -> Dict:
        """
        Retorna resumo de saúde de todos os discos.

        No Windows: usa sempre o Get-PhysicalDisk (WMI) como fonte
        canônica de drives, pois o 'smartctl --scan' retorna aliases
        (SAT, CSMI, etc.) que causam entradas duplicadas.

        No Linux/macOS: usa smartctl quando disponível.
        """
        if os.name == 'nt':
            # Windows: WMI é sempre a fonte confiável de contagem de drives
            return self._get_wmi_health_summary()

        # Linux / macOS: usa smartctl se disponível
        if not self.smartctl_path:
            return {
                'total_drives': 0, 'healthy': 0, 'warning': 0,
                'critical': 0, 'unknown': 0, 'drives': [],
                'timestamp': datetime.now().isoformat()
            }

        drives_info = self.get_all_drives_info()

        healthy  = sum(1 for d in drives_info if d.get('overall_status') == 'healthy')
        warning  = sum(1 for d in drives_info if d.get('overall_status') == 'warning')
        critical = sum(1 for d in drives_info if d.get('overall_status') == 'critical')
        unknown  = sum(1 for d in drives_info if d.get('overall_status') in ['unknown', 'error'])

        return {
            'total_drives': len(drives_info),
            'healthy':  healthy,
            'warning':  warning,
            'critical': critical,
            'unknown':  unknown,
            'drives':   drives_info,
            'timestamp': datetime.now().isoformat()
        }


    @staticmethod
    def _fmt_bytes(b: int) -> str:
        """Formata bytes para string legível"""
        for u in ['B', 'KB', 'MB', 'GB', 'TB']:
            if b < 1024:
                return f"{b:.1f} {u}"
            b /= 1024
        return f"{b:.1f} PB"

    def _get_wmi_health_summary(self) -> Dict:
        """
        Coleta dados SMART + letras de unidade no Windows usando PowerShell.

        Correlação unificada por FriendlyName:
        - Get-Disk → dados principais (Number, FriendlyName, Size, IsBoot, HealthStatus)
        - Get-PhysicalDisk | Get-StorageReliabilityCounter → metrics SMART
        - Get-Disk | Get-Partition | Get-Volume → letras de unidade por DiskNumber

        Usar Get-Disk.Number como chave de volume (não index de PhysicalDisk)
        elimina o bug de letras trocadas.
        """
        import csv, io
        try:
            # ── Query 1: discos via Get-Disk (fonte canônica de DiskNumber) ────
            ps_disk = (
                "Get-Disk | Sort-Object Number | "
                "Select-Object Number,FriendlyName,"
                "@{N='SizeBytes';E={$_.Size}},HealthStatus,IsBoot,"
                "OperationalStatus,SerialNumber | "
                "ConvertTo-Csv -NoTypeInformation"
            )
            out_disk = subprocess.check_output(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_disk],
                text=True, creationflags=0x08000000, timeout=15
            )

            # ── Query 2: tipo de mídia via Get-PhysicalDisk ───────────────────
            ps_phys = (
                "Get-PhysicalDisk | "
                "Select-Object FriendlyName,MediaType,SerialNumber | "
                "ConvertTo-Csv -NoTypeInformation"
            )
            try:
                out_phys = subprocess.check_output(
                    ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_phys],
                    text=True, creationflags=0x08000000, timeout=10
                )
            except Exception:
                out_phys = ""

            # ── Query 3: métricas SMART por FriendlyName ──────────────────────
            ps_smart = (
                "Get-PhysicalDisk | ForEach-Object { "
                "$disk=$_; "
                "try { $rc = $disk | Get-StorageReliabilityCounter -ErrorAction Stop } "
                "catch { $rc = [PSCustomObject]@{Temperature=$null;PowerOnHours=$null;Wear=$null;PowerCycleCount=$null} }; "
                "[PSCustomObject]@{ "
                "  FriendlyName=$disk.FriendlyName; "
                "  Temperature=$rc.Temperature; "
                "  PowerOnHours=$rc.PowerOnHours; "
                "  Wear=$rc.Wear; "
                "  PowerCycleCount=$rc.PowerCycleCount "
                "} } | ConvertTo-Csv -NoTypeInformation"
            )
            try:
                out_smart = subprocess.check_output(
                    ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_smart],
                    text=True, creationflags=0x08000000, timeout=20
                )
            except Exception:
                out_smart = ""

            # ── Query 4: letras de unidade por DiskNumber ─────────────────────
            ps_vol = (
                "Get-Disk | ForEach-Object { $d=$_; "
                "Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue | "
                "ForEach-Object { $p=$_; "
                "Get-Volume -Partition $p -ErrorAction SilentlyContinue | "
                "Select-Object @{N='DiskNum';E={$d.Number}},DriveLetter,"
                "@{N='IsBoot';E={$d.IsBoot}} } } | ConvertTo-Csv -NoTypeInformation"
            )
            try:
                out_vol = subprocess.check_output(
                    ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_vol],
                    text=True, creationflags=0x08000000, timeout=12
                )
            except Exception:
                out_vol = ""

            # ── Parse Get-PhysicalDisk: MediaType por FriendlyName ────────────
            media_by_name: dict = {}
            for row in csv.DictReader(io.StringIO(out_phys.strip())):
                name = row.get('FriendlyName', '').strip()
                mt   = row.get('MediaType', '').strip()
                if name:
                    media_by_name[name] = mt

            # ── Parse métricas SMART por FriendlyName ─────────────────────────
            def _int(v):
                v = (v or '').strip()
                return int(v) if v.lstrip('-').isdigit() else None

            smart_by_name: dict = {}
            for row in csv.DictReader(io.StringIO(out_smart.strip())):
                name = row.get('FriendlyName', '').strip()
                if name:
                    smart_by_name[name] = {
                        'temperature':    _int(row.get('Temperature')),
                        'power_on_hours': _int(row.get('PowerOnHours')),
                        'wear':           _int(row.get('Wear')),
                        'cycles':         _int(row.get('PowerCycleCount')),
                    }

            # ── Parse letras de unidade por DiskNumber ────────────────────────
            mounts:  dict = {}   # { disk_num: 'C:' }
            is_boot: dict = {}   # { disk_num: True }
            for row in csv.DictReader(io.StringIO(out_vol.strip())):
                dnum_s = row.get('DiskNum', '').strip()
                letter = row.get('DriveLetter', '').strip().rstrip('\\').strip()
                boot_s = row.get('IsBoot', '').strip().lower()
                if dnum_s.isdigit() and letter:
                    dn = int(dnum_s)
                    if dn not in mounts:
                        mounts[dn] = letter.rstrip('\\') + ':'
                    if boot_s in ('true', '1'):
                        is_boot[dn] = True

            smartctl_map = self._get_windows_smartctl_map()

            # ── Constrói drives_info usando Get-Disk como master ──────────────
            drives_info = []

            for row in csv.DictReader(io.StringIO(out_disk.strip())):
                num_s  = row.get('Number', '').strip()
                model  = row.get('FriendlyName', '').strip() or 'Disco Desconhecido'
                serial = row.get('SerialNumber', '').strip()
                boot   = row.get('IsBoot', '').strip().lower() in ('true', '1')
                try:
                    size = int(row.get('SizeBytes', '0').strip() or '0')
                except ValueError:
                    size = 0

                disk_num    = int(num_s) if num_s.isdigit() else None
                health_raw  = row.get('HealthStatus', '').strip()
                op_raw      = row.get('OperationalStatus', '').strip()
                media_type  = media_by_name.get(model, row.get('MediaType', '').strip())

                if health_raw in ('Healthy', '3'):
                    overall_status = 'healthy'
                elif health_raw in ('Warning', '4'):
                    overall_status = 'warning'
                elif health_raw in ('Unhealthy', 'Critical', '5'):
                    overall_status = 'critical'
                else:
                    overall_status = 'unknown'

                is_ssd = media_type in ('SSD', '4')

                # SMART metrics — keyed by FriendlyName (reliable)
                sm  = smart_by_name.get(model, {})
                temp = sm.get('temperature')
                poh  = sm.get('power_on_hours')
                wear = sm.get('wear')
                cyc  = sm.get('cycles')

                # Volume / boot — keyed by Get-Disk.Number (reliable)
                mountpt   = mounts.get(disk_num) if disk_num is not None else None
                is_system = boot or is_boot.get(disk_num, False)
                smartctl_info = (
                    smartctl_map.get(f'serial:{self._normalize_key(serial)}')
                    or smartctl_map.get(f'model:{self._normalize_key(model)}')
                )
                unsafe_shutdowns = None
                media_errors = None
                error_log_entries = None
                available_spare = None
                percentage_used = None

                attributes = []
                if smartctl_info:
                    is_ssd = is_ssd or smartctl_info.is_ssd
                    if not serial:
                        serial = smartctl_info.serial
                    temp = smartctl_info.temperature if temp is None else temp
                    poh = smartctl_info.power_on_hours if poh is None else poh
                    cyc = smartctl_info.power_cycle_count if cyc is None else cyc
                    unsafe_shutdowns = smartctl_info.unsafe_shutdowns
                    media_errors = smartctl_info.media_errors
                    error_log_entries = smartctl_info.error_log_entries
                    available_spare = smartctl_info.available_spare
                    percentage_used = smartctl_info.percentage_used
                    if is_ssd and smartctl_info.estimated_life is not None:
                        wear = smartctl_info.estimated_life
                    attributes = [
                        {
                            'id': a.id,
                            'name': a.name,
                            'value': a.value,
                            'worst': a.worst,
                            'threshold': a.threshold,
                            'raw_value': a.raw_value,
                            'status': a.status,
                            'is_critical': a.is_critical,
                            'is_warning': a.is_warning,
                        }
                        for a in smartctl_info.attributes
                    ]
                    if smartctl_info.overall_status.value in ('warning', 'critical'):
                        overall_status = smartctl_info.overall_status.value
                elif not is_ssd:
                    wear = None

                poh_fmt = None
                if poh is not None:
                    poh_fmt = f"{poh // 24}d {poh % 24}h" if poh >= 24 else f"{poh}h"

                drives_info.append({
                    'device':                   f'\\\\.\\PHYSICALDRIVE{disk_num}' if disk_num is not None else model,
                    'model':                    model,
                    'serial':                   serial,
                    'capacity_formatted':       self._fmt_bytes(size),
                    'overall_status':           overall_status,
                    'smart_enabled':            True,
                    'is_ssd':                   is_ssd,
                    'mountpoint':               mountpt,
                    'is_system':                is_system,
                    'temperature':              temp,
                    'power_on_hours_formatted': poh_fmt,
                    'power_on_hours_raw':       poh,
                    'estimated_life_percent':   wear if is_ssd else None,
                    'power_cycle_count':        cyc,
                    'unsafe_shutdowns':         unsafe_shutdowns,
                    'media_errors':             media_errors,
                    'error_log_entries':        error_log_entries,
                    'available_spare':          available_spare,
                    'percentage_used':          percentage_used,
                    'attributes':               attributes,
                    'operational_status':       op_raw,
                })

            healthy = sum(1 for d in drives_info if d['overall_status'] == 'healthy')
            warning = sum(1 for d in drives_info if d['overall_status'] == 'warning')
            critical = sum(1 for d in drives_info if d['overall_status'] == 'critical')
            unknown = sum(1 for d in drives_info if d['overall_status'] not in ('healthy', 'warning', 'critical'))

            return {
                'total_drives': len(drives_info),
                'healthy':  healthy,
                'warning':  warning,
                'critical': critical,
                'unknown':  unknown,
                'drives':   drives_info,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Erro no WMI/PowerShell fallback: {e}")
            return self._get_wmic_fallback()

    def _get_wmic_fallback(self) -> Dict:
        """Último recurso — WMIC simples para listar drives"""
        try:
            output = subprocess.check_output(
                ['wmic', 'diskdrive', 'get', 'DeviceID,Model,Size,Status'],
                text=True, creationflags=0x08000000, timeout=10
            )
            drives_info = []
            healthy = warning = critical = unknown = 0
            lines = [l.strip() for l in output.strip().splitlines() if l.strip()][1:]
            for line in lines:
                parts = line.split()
                if not parts:
                    continue
                device_id  = parts[0]
                status_str = parts[-1].upper() if parts else ''
                try:
                    size = int(parts[-2])
                except (ValueError, IndexError):
                    size = 0
                model = ' '.join(parts[1:-2]) if len(parts) > 2 else 'Desconhecido'

                if status_str == 'OK':
                    overall_status, healthy = 'healthy', healthy + 1
                elif status_str.startswith('PRED'):
                    overall_status, warning = 'warning', warning + 1
                else:
                    overall_status, unknown = 'unknown', unknown + 1

                drives_info.append({
                    'device': device_id, 'model': model,
                    'capacity_formatted': self._fmt_bytes(size),
                    'overall_status': overall_status,
                    'smart_enabled': False, 'is_ssd': False,
                    'temperature': None, 'power_on_hours_formatted': None,
                    'power_on_hours_raw': None, 'power_cycle_count': None,
                    'unsafe_shutdowns': None, 'media_errors': None,
                    'error_log_entries': None, 'available_spare': None,
                    'percentage_used': None,
                    'estimated_life_percent': None, 'attributes': [],
                })
            return {
                'total_drives': len(drives_info), 'healthy': healthy, 'warning': warning,
                'critical': critical, 'unknown': unknown, 'drives': drives_info,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as ex:
            logger.error(f"WMIC fallback também falhou: {ex}")
            return {
                'total_drives': 0, 'healthy': 0, 'warning': 0, 'critical': 0, 'unknown': 0,
                'drives': [], 'timestamp': datetime.now().isoformat()
            }


# Instância global
_smart_monitor: Optional[SMARTMonitor] = None


def get_smart_monitor() -> SMARTMonitor:
    """Retorna instância global do SMARTMonitor"""
    global _smart_monitor
    if _smart_monitor is None:
        _smart_monitor = SMARTMonitor()
    return _smart_monitor


if __name__ == '__main__':
    # Teste do monitor
    logging.basicConfig(level=logging.INFO)
    
    monitor = SMARTMonitor()
    
    print(f"SMART disponível: {monitor.is_available()}")
    print(f"smartctl: {monitor.smartctl_path}")
    
    if monitor.is_available():
        print("\nDrives encontrados:")
        for drive in monitor.scan_drives():
            print(f"  {drive['device']} ({drive.get('model', 'Unknown')})")
        
        print("\nInformações SMART:")
        for info in monitor.get_all_drives_info():
            print(f"\n  {info['device']}:")
            print(f"    Modelo: {info['model']}")
            print(f"    Status: {info['overall_status']}")
            print(f"    Temperatura: {info['temperature']}°C")
            print(f"    Horas de uso: {info['power_on_hours_formatted']}")
