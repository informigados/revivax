"""
RevivaX - Core Package
"""

from .scanner import (
    DiskScanner, ScanResult, ScanMode, get_available_drives,
    FILE_SIGNATURES, get_extension_category,
)
from .carver import FileCarver, CarveResult
from .recovery import RecoveryManager, RecoveryJob, RecoveryStatus, get_recovery_manager
from .smart_monitor import SMARTMonitor, SMARTInfo, SMARTStatus, get_smart_monitor

__all__ = [
    'DiskScanner',
    'ScanResult', 
    'ScanMode',
    'get_available_drives',
    'FILE_SIGNATURES',
    'get_extension_category',
    'FileCarver',
    'CarveResult',
    'RecoveryManager',
    'RecoveryJob',
    'RecoveryStatus',
    'get_recovery_manager',
    'SMARTMonitor',
    'SMARTInfo',
    'SMARTStatus',
    'get_smart_monitor',
]

__version__ = '1.0.0'
