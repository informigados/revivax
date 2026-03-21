"""
RevivaX - Minimal NTFS helpers
Leitura suficiente de NTFS para localizar arquivos deletados por pasta via $MFT.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Dict, Iterable, List, Optional


@dataclass
class NtfsVolumeInfo:
    bytes_per_sector: int
    sectors_per_cluster: int
    cluster_size: int
    mft_lcn: int
    mft_record_size: int
    index_record_size: int


@dataclass
class NtfsDataRun:
    lcn: Optional[int]
    length_clusters: int


@dataclass
class NtfsRecord:
    number: int
    name: str = ""
    parent_reference: Optional[int] = None
    is_directory: bool = False
    is_in_use: bool = False
    size: int = 0
    allocated_size: int = 0
    data_runs: List[NtfsDataRun] = field(default_factory=list)
    resident_data: Optional[bytes] = None
    record_offset: int = 0
    full_path: str = ""


def parse_boot_sector(sector: bytes) -> NtfsVolumeInfo:
    if len(sector) < 80:
        raise ValueError("Boot sector NTFS inválido ou incompleto.")

    if sector[3:11] != b"NTFS    ":
        raise ValueError("O volume não reporta assinatura NTFS.")

    bytes_per_sector = struct.unpack_from("<H", sector, 11)[0]
    sectors_per_cluster = sector[13]
    cluster_size = bytes_per_sector * sectors_per_cluster
    mft_lcn = struct.unpack_from("<Q", sector, 48)[0]

    record_size_raw = struct.unpack_from("<b", sector, 64)[0]
    if record_size_raw < 0:
        mft_record_size = 1 << (-record_size_raw)
    else:
        mft_record_size = record_size_raw * cluster_size

    index_size_raw = struct.unpack_from("<b", sector, 68)[0]
    if index_size_raw < 0:
        index_record_size = 1 << (-index_size_raw)
    else:
        index_record_size = index_size_raw * cluster_size

    if bytes_per_sector <= 0 or cluster_size <= 0 or mft_record_size <= 0:
        raise ValueError("Parâmetros NTFS inválidos no boot sector.")

    return NtfsVolumeInfo(
        bytes_per_sector=bytes_per_sector,
        sectors_per_cluster=sectors_per_cluster,
        cluster_size=cluster_size,
        mft_lcn=mft_lcn,
        mft_record_size=mft_record_size,
        index_record_size=index_record_size,
    )


def apply_update_sequence(record: bytes, bytes_per_sector: int) -> bytes:
    fixed = bytearray(record)
    usa_offset = struct.unpack_from("<H", fixed, 4)[0]
    usa_count = struct.unpack_from("<H", fixed, 6)[0]

    if usa_offset == 0 or usa_count <= 1:
        return bytes(fixed)

    usa_size = usa_count * 2
    if usa_offset + usa_size > len(fixed):
        raise ValueError("Update Sequence Array fora do record NTFS.")

    usa = fixed[usa_offset:usa_offset + usa_size]
    sequence_number = usa[:2]
    replacements = [usa[i:i + 2] for i in range(2, len(usa), 2)]

    for index, replacement in enumerate(replacements, start=1):
        end = (bytes_per_sector * index) - 2
        if end + 2 > len(fixed):
            break
        if fixed[end:end + 2] != sequence_number:
            raise ValueError("Falha ao validar fixup sequence de record NTFS.")
        fixed[end:end + 2] = replacement

    return bytes(fixed)


def decode_runlist(runlist: bytes) -> List[NtfsDataRun]:
    runs: List[NtfsDataRun] = []
    cursor = 0
    current_lcn = 0

    while cursor < len(runlist):
        header = runlist[cursor]
        cursor += 1
        if header == 0:
            break

        length_size = header & 0x0F
        offset_size = (header >> 4) & 0x0F
        if length_size == 0 or cursor + length_size + offset_size > len(runlist):
            break

        run_length = int.from_bytes(runlist[cursor:cursor + length_size], "little", signed=False)
        cursor += length_size

        run_offset = 0
        if offset_size:
            raw_offset = runlist[cursor:cursor + offset_size]
            sign_fill = b"\xff" if raw_offset[-1] & 0x80 else b"\x00"
            run_offset = int.from_bytes(raw_offset + sign_fill * (8 - offset_size), "little", signed=True)
            cursor += offset_size

        if offset_size == 0:
            runs.append(NtfsDataRun(lcn=None, length_clusters=run_length))
            continue

        current_lcn += run_offset
        runs.append(NtfsDataRun(lcn=current_lcn, length_clusters=run_length))

    return runs


def parse_file_record(record: bytes, volume_info: NtfsVolumeInfo, record_number: int, record_offset: int = 0) -> Optional[NtfsRecord]:
    if len(record) < volume_info.mft_record_size or record[:4] != b"FILE":
        return None

    fixed = apply_update_sequence(record, volume_info.bytes_per_sector)
    flags = struct.unpack_from("<H", fixed, 22)[0]
    first_attr_offset = struct.unpack_from("<H", fixed, 20)[0]

    parsed = NtfsRecord(
        number=record_number,
        is_in_use=bool(flags & 0x0001),
        is_directory=bool(flags & 0x0002),
        record_offset=record_offset,
    )

    best_name_score = -1
    cursor = first_attr_offset

    while cursor + 8 <= len(fixed):
        attr_type = struct.unpack_from("<I", fixed, cursor)[0]
        if attr_type == 0xFFFFFFFF:
            break

        attr_length = struct.unpack_from("<I", fixed, cursor + 4)[0]
        if attr_length <= 0 or cursor + attr_length > len(fixed):
            break

        non_resident = fixed[cursor + 8]
        name_length = fixed[cursor + 9]

        if attr_type == 0x30 and non_resident == 0:
            value_length = struct.unpack_from("<I", fixed, cursor + 16)[0]
            value_offset = struct.unpack_from("<H", fixed, cursor + 20)[0]
            start = cursor + value_offset
            end = start + value_length
            if end <= len(fixed) and value_length >= 66:
                value = fixed[start:end]
                parent_reference = struct.unpack_from("<Q", value, 0)[0] & 0x0000FFFFFFFFFFFF
                allocated_size = struct.unpack_from("<Q", value, 40)[0]
                real_size = struct.unpack_from("<Q", value, 48)[0]
                file_flags = struct.unpack_from("<I", value, 56)[0]
                file_name_length = value[64]
                namespace = value[65]
                name_start = 66
                name_end = name_start + (file_name_length * 2)
                if name_end <= len(value):
                    try:
                        file_name = value[name_start:name_end].decode("utf-16le", errors="ignore")
                    except UnicodeDecodeError:
                        file_name = ""
                    score = 0 if namespace == 2 else 10
                    score += len(file_name)
                    if score > best_name_score:
                        parsed.name = file_name
                        parsed.parent_reference = int(parent_reference)
                        parsed.allocated_size = int(allocated_size)
                        parsed.size = int(real_size)
                        parsed.is_directory = bool(file_flags & 0x10000000) or parsed.is_directory
                        best_name_score = score

        if attr_type == 0x80:
            if non_resident == 0:
                value_length = struct.unpack_from("<I", fixed, cursor + 16)[0]
                value_offset = struct.unpack_from("<H", fixed, cursor + 20)[0]
                start = cursor + value_offset
                end = start + value_length
                if end <= len(fixed):
                    parsed.resident_data = bytes(fixed[start:end])
                    parsed.size = int(value_length)
                    parsed.allocated_size = int(value_length)
            else:
                run_offset = struct.unpack_from("<H", fixed, cursor + 32)[0]
                data_size = struct.unpack_from("<Q", fixed, cursor + 48)[0]
                allocated_size = struct.unpack_from("<Q", fixed, cursor + 40)[0]
                run_start = cursor + run_offset
                run_end = cursor + attr_length
                if run_start < run_end <= len(fixed):
                    parsed.data_runs = decode_runlist(bytes(fixed[run_start:run_end]))
                    parsed.size = int(data_size)
                    parsed.allocated_size = int(allocated_size)

        cursor += attr_length
        if name_length and cursor % 8:
            cursor += 8 - (cursor % 8)

    return parsed if parsed.name or parsed.number in (0, 5) else None


def iter_mft_records(
    stream: BinaryIO,
    volume_info: NtfsVolumeInfo,
    max_records: Optional[int] = None,
    stop_after_invalid: int = 128,
) -> Iterable[NtfsRecord]:
    mft_offset = volume_info.mft_lcn * volume_info.cluster_size
    invalid_streak = 0
    record_number = 0

    while max_records is None or record_number < max_records:
        record_offset = mft_offset + (record_number * volume_info.mft_record_size)
        stream.seek(record_offset)
        raw_record = stream.read(volume_info.mft_record_size)
        if len(raw_record) < volume_info.mft_record_size:
            break

        if raw_record[:4] != b"FILE":
            invalid_streak += 1
            if invalid_streak >= stop_after_invalid:
                break
            record_number += 1
            continue

        invalid_streak = 0
        try:
            record = parse_file_record(raw_record, volume_info, record_number, record_offset=record_offset)
        except ValueError:
            record = None

        if record is not None:
            yield record

        record_number += 1


def resolve_folder_record(records: Dict[int, NtfsRecord], components: List[str]) -> Optional[int]:
    current = 5
    for component in components:
        component_fold = component.casefold()
        match = None
        for record in records.values():
            if record.parent_reference != current or not record.is_directory or not record.name:
                continue
            if record.name.casefold() != component_fold:
                continue
            if match is None or (record.is_in_use and not match.is_in_use):
                match = record
        if match is None:
            return None
        current = match.number
    return current


def build_full_paths(records: Dict[int, NtfsRecord]) -> None:
    cache: Dict[int, str] = {}

    def _resolve(record_number: int, seen: Optional[set] = None) -> str:
        if record_number in cache:
            return cache[record_number]
        if record_number == 5:
            cache[record_number] = ""
            return ""

        seen = seen or set()
        if record_number in seen:
            return ""
        seen.add(record_number)

        record = records.get(record_number)
        if not record or not record.name:
            return ""

        parent_path = _resolve(record.parent_reference or 5, seen)
        full_path = f"{parent_path}\\{record.name}" if parent_path else record.name
        cache[record_number] = full_path
        return full_path

    for number, record in records.items():
        record.full_path = _resolve(number)


def collect_descendants(records: Dict[int, NtfsRecord], root_record: int) -> set:
    descendants = {root_record}
    changed = True
    while changed:
        changed = False
        for record in records.values():
            if record.number in descendants:
                continue
            if record.parent_reference in descendants:
                descendants.add(record.number)
                changed = True
    return descendants


def read_boot_sector(stream: BinaryIO) -> NtfsVolumeInfo:
    stream.seek(0)
    return parse_boot_sector(stream.read(512))


def open_binary_stream(source: str) -> BinaryIO:
    if isinstance(source, (io.BufferedIOBase, io.BytesIO)):
        return source
    return open(source, "rb")
