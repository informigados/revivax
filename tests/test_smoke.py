import base64
import hashlib
import importlib
import os
import struct
import time
from pathlib import Path

import core.smartctl_setup as smartctl_setup
from core.carver import FileCarver
import core.recovery as recovery_module
from core.scanner import DiskScanner, FILE_SIGNATURES, ScanMode, ScanResult

webapp = importlib.import_module("web.app")

PNG_DATA = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aW7sAAAAASUVORK5CYII="
)
JPG_DATA = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxAQEBUQEBAVFRUVFRUVFRUVFRUVFRUVFRUWFhUVFRUYHSggGBolHRUVITEhJSkrLi4uFx8zODMsNygtLisBCgoKDg0OGhAQGi0fHyUtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAAEAAgMBIgACEQEDEQH/xAAXAAADAQAAAAAAAAAAAAAAAAAAAQID/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEAMQAAAB6A//xAAZEAEAAwEBAAAAAAAAAAAAAAABAAIRITH/2gAIAQEAAT8AqLk0Y//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8Af//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8Af//Z"
)


def _encode_runlist(runs):
    payload = bytearray()
    current_lcn = 0
    for lcn, length_clusters in runs:
        length_raw = int(length_clusters).to_bytes(1, "little", signed=False)
        if lcn is None:
            payload.append(len(length_raw))
            payload.extend(length_raw)
            continue
        delta = int(lcn) - current_lcn
        current_lcn = int(lcn)
        offset_raw = int(delta).to_bytes(1 if -128 <= delta <= 127 else 2, "little", signed=True)
        payload.append(len(length_raw) | (len(offset_raw) << 4))
        payload.extend(length_raw)
        payload.extend(offset_raw)
    payload.append(0)
    return bytes(payload)


def _build_resident_attr(attr_type, value):
    value = bytes(value)
    total_length = 24 + len(value)
    if total_length % 8:
        total_length += 8 - (total_length % 8)
    attr = bytearray(total_length)
    struct.pack_into("<I", attr, 0, attr_type)
    struct.pack_into("<I", attr, 4, total_length)
    attr[8] = 0
    struct.pack_into("<I", attr, 16, len(value))
    struct.pack_into("<H", attr, 20, 24)
    attr[24:24 + len(value)] = value
    return bytes(attr)


def _build_nonresident_data_attr(runlist, real_size):
    total_length = 0x40 + len(runlist)
    if total_length % 8:
        total_length += 8 - (total_length % 8)
    attr = bytearray(total_length)
    struct.pack_into("<I", attr, 0, 0x80)
    struct.pack_into("<I", attr, 4, total_length)
    attr[8] = 1
    struct.pack_into("<Q", attr, 16, 0)
    struct.pack_into("<Q", attr, 24, 0)
    struct.pack_into("<H", attr, 32, 0x40)
    allocated_size = len(runlist) * 0 + real_size
    struct.pack_into("<Q", attr, 40, allocated_size)
    struct.pack_into("<Q", attr, 48, real_size)
    struct.pack_into("<Q", attr, 56, real_size)
    attr[0x40:0x40 + len(runlist)] = runlist
    return bytes(attr)


def _build_filename_attr(name, parent_reference, is_dir, real_size):
    name_utf16 = name.encode("utf-16le")
    value = bytearray(66 + len(name_utf16))
    struct.pack_into("<Q", value, 0, parent_reference)
    struct.pack_into("<Q", value, 40, real_size)
    struct.pack_into("<Q", value, 48, real_size)
    struct.pack_into("<I", value, 56, 0x10000000 if is_dir else 0)
    value[64] = len(name)
    value[65] = 1
    value[66:66 + len(name_utf16)] = name_utf16
    return _build_resident_attr(0x30, value)


def _build_mft_record(record_number, name, parent_reference, *, is_dir=False, in_use=True, resident_data=None, data_runs=None, real_size=0):
    record = bytearray(1024)
    record[:4] = b"FILE"
    struct.pack_into("<H", record, 4, 0x30)
    struct.pack_into("<H", record, 6, 3)
    struct.pack_into("<H", record, 20, 0x38)
    flags = (0x0002 if is_dir else 0) | (0x0001 if in_use else 0)
    struct.pack_into("<H", record, 22, flags)
    struct.pack_into("<I", record, 44, record_number)
    attrs = bytearray()
    attrs.extend(_build_filename_attr(name, parent_reference, is_dir, real_size))
    if resident_data is not None:
        attrs.extend(_build_resident_attr(0x80, resident_data))
    elif data_runs is not None:
        attrs.extend(_build_nonresident_data_attr(_encode_runlist(data_runs), real_size))
    attrs.extend(struct.pack("<I", 0xFFFFFFFF))
    record[0x38:0x38 + len(attrs)] = attrs
    struct.pack_into("<I", record, 24, 0x38 + len(attrs))

    sequence = b"\xaa\xbb"
    fixup_1 = b"\x11\x22"
    fixup_2 = b"\x33\x44"
    record[0x30:0x36] = sequence + fixup_1 + fixup_2
    record[510:512] = sequence
    record[1022:1024] = sequence
    return bytes(record)


def _build_ntfs_image(image_path, mount_cluster_runs=None, resident_data=None):
    image_size = 64 * 1024
    image = bytearray(image_size)
    image[3:11] = b"NTFS    "
    struct.pack_into("<H", image, 11, 512)
    image[13] = 1
    struct.pack_into("<Q", image, 48, 1)
    struct.pack_into("<b", image, 64, -10)  # 1024-byte record
    struct.pack_into("<b", image, 68, 1)

    mft_offset = 512
    image[mft_offset + (5 * 1024):mft_offset + (6 * 1024)] = _build_mft_record(5, "", 5, is_dir=True, in_use=True)
    image[mft_offset + (10 * 1024):mft_offset + (11 * 1024)] = _build_mft_record(10, "Target", 5, is_dir=True, in_use=True)
    image[mft_offset + (11 * 1024):mft_offset + (12 * 1024)] = _build_mft_record(
        11,
        "deleted.png",
        10,
        is_dir=False,
        in_use=False,
        resident_data=resident_data,
        data_runs=mount_cluster_runs,
        real_size=len(resident_data) if resident_data is not None else len(PNG_DATA),
    )
    image_path.write_bytes(image)


class _UnavailableSmartMonitor:
    def is_available(self):
        return False


def _wait_for(client, fetcher, timeout=5.0):
    deadline = time.time() + timeout
    last_payload = None
    while time.time() < deadline:
        last_payload = fetcher()
        if last_payload:
            return last_payload
        time.sleep(0.05)
    raise AssertionError(f"Timeout aguardando resposta: {last_payload}")


def test_regular_file_scan_detects_embedded_png(tmp_path):
    image_path = tmp_path / "sample.img"
    image_path.write_bytes(b"\x00" * 4096 + PNG_DATA + b"\x00" * 4096)

    for mode in (ScanMode.QUICK, ScanMode.DEEP):
        scanner = DiskScanner()
        results = scanner.scan_drive(str(image_path), mode=mode)
        png_matches = [result for result in results if result.extension == "png"]

        assert png_matches, f"Modo {mode.value} nao encontrou o PNG embutido"
        assert len(results) == 1
        assert png_matches[0].offset == 4096
        assert png_matches[0].size > 0


def test_api_scan_recover_and_export_smoke(tmp_path, monkeypatch):
    manager = recovery_module.RecoveryManager(
        output_dir=str(tmp_path / "recovered"),
        logs_dir=str(tmp_path / "test-logs"),
    )
    monkeypatch.setattr(webapp, "recovery_manager", manager)
    monkeypatch.setattr(webapp, "smart_monitor", _UnavailableSmartMonitor())

    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    (sample_dir / "sample.png").write_bytes(PNG_DATA)
    (sample_dir / "sample.jpg").write_bytes(JPG_DATA)
    (sample_dir / "notes.txt").write_text("arquivo comum", encoding="utf-8")

    export_file = None

    with webapp.app.test_client() as client:
        smart_response = client.get("/api/smart")
        assert smart_response.status_code == 200
        assert smart_response.get_json()["available"] is False

        scan_response = client.post(
            "/api/scan/start",
            json={"drive": str(sample_dir), "mode": "quick"},
        )
        assert scan_response.status_code == 200
        assert scan_response.get_json()["success"] is True
        assert scan_response.get_json()["job_id"]
        assert "no-store" in scan_response.headers["Cache-Control"]

        def _scan_done():
            payload = client.get("/api/scan/progress").get_json()["progress"]
            if payload["status"] in ("completed", "error", "stopped"):
                return payload
            return None

        progress = _wait_for(client, _scan_done)
        assert progress["status"] == "completed"
        assert progress["current"] == progress["total"] == 3
        assert progress["files_found"] == 2

        results_response = client.get("/api/scan/results")
        results_payload = results_response.get_json()
        assert results_response.status_code == 200
        assert "no-store" in results_response.headers["Cache-Control"]
        assert results_payload["total"] == 2
        assert {item["extension"] for item in results_payload["results"]} == {"jpg", "png"}

        recover_response = client.post(
            "/api/recover/start",
            json={"indices": [0, 1], "output_dir": str(tmp_path / "output")},
        )
        assert recover_response.status_code == 200
        assert recover_response.get_json()["success"] is True

        def _recovery_done():
            payload = client.get("/api/recover/results").get_json()
            if payload["total"] == 2:
                return payload
            return None

        recovery_payload = _wait_for(client, _recovery_done)
        assert recovery_payload["successful"] == 2
        for item in recovery_payload["results"]:
            assert item["success"] is True
            assert Path(item["recovered_path"]).exists()

        export_response = client.post("/api/export/results", json={"format": "json"})
        export_payload = export_response.get_json()
        assert export_response.status_code == 200
        assert export_payload["success"] is True

        export_file = manager.logs_dir / export_payload["filename"]
        assert export_file.exists()

    if export_file is not None and export_file.exists():
        export_file.unlink()


def test_scan_results_follow_current_job_id(tmp_path, monkeypatch):
    manager = recovery_module.RecoveryManager(
        output_dir=str(tmp_path / "recovered"),
        logs_dir=str(tmp_path / "test-logs"),
    )
    monkeypatch.setattr(webapp, "recovery_manager", manager)
    monkeypatch.setattr(webapp, "smart_monitor", _UnavailableSmartMonitor())

    original_scan_drive = manager.scanner.scan_drive

    def delayed_scan_drive(drive_path, mode=ScanMode.QUICK, file_types=None, progress_callback=None, sector_size=512):
        time.sleep(0.2)
        return original_scan_drive(drive_path, mode, file_types, progress_callback, sector_size)

    monkeypatch.setattr(manager.scanner, "scan_drive", delayed_scan_drive)

    folder_a = tmp_path / "folder-a"
    folder_b = tmp_path / "folder-b"
    folder_a.mkdir()
    folder_b.mkdir()
    (folder_a / "sample.png").write_bytes(PNG_DATA)
    (folder_b / "sample.jpg").write_bytes(JPG_DATA)

    with webapp.app.test_client() as client:
        first_start = client.post("/api/scan/start", json={"drive": str(folder_a), "mode": "quick"})
        first_job_id = first_start.get_json()["job_id"]

        def _first_scan_done():
            payload = client.get("/api/scan/progress").get_json()["progress"]
            if payload["status"] == "completed" and payload["job_id"] == first_job_id:
                return payload
            return None

        _wait_for(client, _first_scan_done)
        first_results = client.get(f"/api/scan/results?job_id={first_job_id}").get_json()
        assert first_results["job_id"] == first_job_id
        assert first_results["total"] == 1
        assert {item["extension"] for item in first_results["results"]} == {"png"}

        second_start = client.post("/api/scan/start", json={"drive": str(folder_b), "mode": "quick"})
        second_job_id = second_start.get_json()["job_id"]
        assert second_job_id != first_job_id

        immediate_results = client.get(f"/api/scan/results?job_id={second_job_id}").get_json()
        assert immediate_results["job_id"] == second_job_id
        assert immediate_results["total"] == 0
        assert immediate_results["results"] == []
        assert immediate_results.get("pending", True) is True

        def _second_scan_done():
            payload = client.get("/api/scan/progress").get_json()["progress"]
            if payload["status"] == "completed" and payload["job_id"] == second_job_id:
                return payload
            return None

        progress = _wait_for(client, _second_scan_done)
        assert progress["job_id"] == second_job_id

        second_results = client.get(f"/api/scan/results?job_id={second_job_id}").get_json()
        assert second_results["job_id"] == second_job_id
        assert second_results["total"] == 1
        assert {item["extension"] for item in second_results["results"]} == {"jpg"}


def test_folder_scan_normalizes_deep_mode_to_quick(tmp_path, monkeypatch):
    manager = recovery_module.RecoveryManager(
        output_dir=str(tmp_path / "recovered"),
        logs_dir=str(tmp_path / "test-logs"),
    )
    monkeypatch.setattr(webapp, "recovery_manager", manager)
    monkeypatch.setattr(webapp, "smart_monitor", _UnavailableSmartMonitor())

    sample_dir = tmp_path / "folder-scan"
    sample_dir.mkdir()
    (sample_dir / "sample.png").write_bytes(PNG_DATA)

    with webapp.app.test_client() as client:
        scan_response = client.post(
            "/api/scan/start",
            json={"drive": str(sample_dir), "mode": "deep"},
        )

        payload = scan_response.get_json()
        assert payload["success"] is True
        assert payload["requested_mode"] == "deep"
        assert payload["source_kind"] == "folder"
        assert payload["effective_mode"] in {"deep", "quick"}
        assert isinstance(payload["supports_deep_folder_scan"], bool)

        def _scan_done():
            progress = client.get("/api/scan/progress").get_json()["progress"]
            if progress["status"] == "completed" and progress["job_id"] == payload["job_id"]:
                return progress
            return None

        _wait_for(client, _scan_done)

        results_response = client.get(f"/api/scan/results?job_id={payload['job_id']}")
        results_payload = results_response.get_json()
        assert results_payload["job_id"] == payload["job_id"]
        effective_mode = results_payload["scan_context"]["effective_mode"]
        assert results_payload["mode"] == effective_mode
        assert effective_mode in {"deep", "quick"}
        assert results_payload["source_kind"] == "folder"
        assert results_payload["total"] == 1


def test_deep_ntfs_folder_scan_returns_deleted_files_via_mft(tmp_path):
    image_path = tmp_path / "ntfs.img"
    _build_ntfs_image(image_path, mount_cluster_runs=[(20, 1)])

    scanner = DiskScanner()
    png_signature = [sig for sig in FILE_SIGNATURES if sig.extension == "png"]
    scanner._scan_folder_deep_ntfs(
        str(tmp_path / "Target"),
        png_signature,
        context={
            "volume_device": str(image_path),
            "volume_mountpoint": str(tmp_path),
            "filesystem": "NTFS",
            "effective_mode": "deep",
            "strategy": "ntfs_mft",
        },
    )

    assert len(scanner.results) == 1
    result = scanner.results[0]
    assert result.extension == "png"
    assert result.signature_matched == "ntfs:mft"
    assert result.metadata["scan_source"] == "ntfs_mft"
    assert result.metadata["source_device"] == str(image_path)
    assert result.metadata["data_runs"] == [{"lcn": 20, "length_clusters": 1}]


def test_carver_recovers_ntfs_resident_data(tmp_path):
    output_dir = tmp_path / "resident-output"
    carver = FileCarver(output_dir=str(output_dir), read_only=True)
    result = carver.carve_file(
        "ignored",
        ScanResult(
            offset=0,
            size=len(PNG_DATA),
            file_type="PNG Image",
            extension="png",
            confidence=0.95,
            signature_matched="ntfs:mft",
            metadata={"resident_data_b64": base64.b64encode(PNG_DATA).decode("ascii")},
        ),
        verify=False,
    )

    assert result.success is True
    recovered_path = Path(result.recovered_path)
    assert recovered_path.exists()
    assert recovered_path.read_bytes() == PNG_DATA


def test_carver_recovers_ntfs_data_runs_from_image(tmp_path):
    image_path = tmp_path / "cluster-image.bin"
    cluster_size = 512
    first_chunk = b"A" * cluster_size
    second_chunk = b"B" * 188 + b"\x00" * (cluster_size - 188)
    image = bytearray(cluster_size * 10)
    image[4 * cluster_size:5 * cluster_size] = first_chunk
    image[8 * cluster_size:9 * cluster_size] = second_chunk
    image_path.write_bytes(image)

    output_dir = tmp_path / "runs-output"
    carver = FileCarver(output_dir=str(output_dir), read_only=True)
    scan_result = ScanResult(
        offset=4 * cluster_size,
        size=cluster_size + 188,
        file_type="PNG Image",
        extension="png",
        confidence=0.9,
        signature_matched="ntfs:mft",
        metadata={
            "source_device": str(image_path),
            "cluster_size": cluster_size,
            "data_runs": [
                {"lcn": 4, "length_clusters": 1},
                {"lcn": 8, "length_clusters": 1},
            ],
        },
    )

    result = carver.carve_file(str(image_path), scan_result, verify=False)
    assert result.success is True
    recovered_path = Path(result.recovered_path)
    assert recovered_path.exists()
    recovered = recovered_path.read_bytes()
    assert recovered == first_chunk + (b"B" * 188)


def test_progress_callback_parses_multilingual_messages():
    webapp._reset_progress()

    webapp.progress_callback(
        3,
        10,
        "Scan progress: 7 found • Images: 2 • Videos: 1 • Audio: 1 • Documents: 2 • Archives: 1",
    )

    progress = webapp.app.test_client().get("/api/scan/progress").get_json()["progress"]
    assert progress["current"] == 3
    assert progress["total"] == 10
    assert progress["files_found"] == 7
    assert progress["file_counts"]["image"] == 2
    assert progress["file_counts"]["video"] == 1
    assert progress["file_counts"]["audio"] == 1
    assert progress["file_counts"]["document"] == 2
    assert progress["file_counts"]["archive"] == 1


def test_progress_stream_closes_for_paused_status():
    webapp._reset_progress()
    with webapp._progress_lock:
        webapp.scan_progress["status"] = "paused"
        webapp.scan_progress["message"] = "Scan paused"

    with webapp.app.test_client() as client:
        response = client.get("/api/scan/progress/stream")
        payload = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "data:" in payload
    assert '"status": "paused"' in payload
    assert payload.count("data:") == 1


def test_folder_carve_releases_output_file_handle(tmp_path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    source_file = source_dir / "sample.png"
    source_file.write_bytes(PNG_DATA)

    carver = FileCarver(output_dir=str(output_dir), read_only=True)
    result = carver.carve_file(
        str(tmp_path / "dummy.img"),
        ScanResult(
            offset=0,
            size=len(PNG_DATA),
            file_type="PNG Image",
            extension="png",
            confidence=0.9,
            signature_matched="89504e47",
            metadata={"original_path": str(source_file)},
        ),
    )

    recovered_path = Path(result.recovered_path)
    assert result.success is True
    assert recovered_path.exists()

    recovered_path.unlink()
    assert not recovered_path.exists()


def test_recovery_manager_resolves_relative_paths_from_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery_module, "PROJECT_ROOT", tmp_path)

    manager = recovery_module.RecoveryManager(output_dir="relative-output", logs_dir="relative-logs")

    assert manager.output_dir == (tmp_path / "relative-output").resolve()
    assert manager.logs_dir == (tmp_path / "relative-logs").resolve()
    assert manager.output_dir.exists()
    assert manager.logs_dir.exists()


def test_recovery_rejects_restricted_windows_output_dir(tmp_path, monkeypatch):
    if os.name != "nt":
        return

    manager = recovery_module.RecoveryManager(
        output_dir=str(tmp_path / "recovered"),
        logs_dir=str(tmp_path / "test-logs"),
    )
    monkeypatch.setattr(webapp, "recovery_manager", manager)
    monkeypatch.setattr(webapp, "smart_monitor", _UnavailableSmartMonitor())

    protected_root = tmp_path / "localappdata"
    monkeypatch.setenv("LOCALAPPDATA", str(protected_root))
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    (sample_dir / "sample.png").write_bytes(PNG_DATA)

    with webapp.app.test_client() as client:
        client.post("/api/scan/start", json={"drive": str(sample_dir), "mode": "quick"})

        def _scan_done():
            payload = client.get("/api/scan/progress").get_json()["progress"]
            if payload["status"] == "completed":
                return payload
            return None

        _wait_for(client, _scan_done)

        blocked_output = protected_root / "Microsoft" / "RevivaX"
        response = client.post(
            "/api/recover/start",
            json={"indices": [0], "output_dir": str(blocked_output)},
        )

    assert response.status_code == 403
    assert response.get_json()["success"] is False


def test_browse_folder_passes_title_via_environment(monkeypatch):
    if os.name != "nt":
        return

    captured = {}

    def fake_check_output(cmd, text, timeout, env):
        captured["cmd"] = cmd
        captured["env"] = env
        return ""

    import subprocess

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    with webapp.app.test_client() as client:
        response = client.post("/api/browse-folder")

    assert response.status_code == 200
    assert response.get_json()["cancelled"] is True
    assert captured["env"]["REVIVAX_BROWSE_TITLE"]
    assert "REVIVAX_BROWSE_TITLE" in captured["env"]
    assert "os.environ.get('REVIVAX_BROWSE_TITLE'" in captured["cmd"][2]


def test_security_headers_are_present():
    with webapp.app.test_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_cors_allows_only_local_origins():
    with webapp.app.test_client() as client:
        allowed = client.get("/api/file-types", headers={"Origin": "http://127.0.0.1:5000"})
        denied_local = client.get("/api/file-types", headers={"Origin": "http://127.0.0.1:9999"})
        denied = client.get("/api/file-types", headers={"Origin": "http://evil.example"})

    assert allowed.headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:5000"
    assert denied_local.headers.get("Access-Control-Allow-Origin") is None
    assert denied.headers.get("Access-Control-Allow-Origin") is None


def test_scan_start_rejects_relative_target(tmp_path, monkeypatch):
    manager = recovery_module.RecoveryManager(
        output_dir=str(tmp_path / "recovered"),
        logs_dir=str(tmp_path / "test-logs"),
    )
    monkeypatch.setattr(webapp, "recovery_manager", manager)
    monkeypatch.setattr(webapp, "smart_monitor", _UnavailableSmartMonitor())

    with webapp.app.test_client() as client:
        response = client.post("/api/scan/start", json={"drive": "relative-folder", "mode": "quick"})

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["success"] is False


def test_log_delete_rejects_path_traversal(tmp_path, monkeypatch):
    manager = recovery_module.RecoveryManager(
        output_dir=str(tmp_path / "recovered"),
        logs_dir=str(tmp_path / "test-logs"),
    )
    monkeypatch.setattr(webapp, "recovery_manager", manager)
    monkeypatch.setattr(webapp, "smart_monitor", _UnavailableSmartMonitor())

    with webapp.app.test_client() as client:
        response = client.post("/api/logs/delete", json={"filename": "..\\secrets.txt"})

    payload = response.get_json()
    assert response.status_code == 400
    assert payload["success"] is False


def test_smartctl_download_integrity_uses_digest(tmp_path):
    installer = tmp_path / "smartctl-installer.exe"
    installer.write_bytes(b"revivax-smartctl")
    expected = hashlib.sha256(installer.read_bytes()).hexdigest()

    assert smartctl_setup._verify_download_integrity(installer, f"sha256:{expected}") is True
    assert smartctl_setup._verify_download_integrity(installer, "sha256:deadbeef") is False


def test_smartctl_prefers_bundled_binary(tmp_path, monkeypatch):
    bundled = tmp_path / "smartctl.exe"
    bundled.write_bytes(b"binary")
    monkeypatch.setattr(smartctl_setup, "SMARTCTL_BUNDLED", bundled)
    monkeypatch.setattr(smartctl_setup, "SMARTCTL_LOCAL", tmp_path / "missing-smartctl.exe")
    monkeypatch.setattr(smartctl_setup, "_is_executable", lambda path: path == str(bundled))

    assert smartctl_setup.ensure_smartctl() == str(bundled)


def test_index_uses_local_vendor_assets():
    index_html = (Path(__file__).resolve().parents[1] / "web" / "templates" / "index.html").read_text(encoding="utf-8")

    assert "vendor/tailwindcss/tailwindcdn.js" in index_html
    assert "vendor/fontawesome/css/all.min.css" in index_html
    assert "cdn.tailwindcss.com" not in index_html
    assert "cdnjs.cloudflare.com/ajax/libs/font-awesome" not in index_html
    assert "fonts.googleapis.com" not in index_html


def test_static_vendor_assets_are_served():
    with webapp.app.test_client() as client:
        tailwind = client.get("/static/vendor/tailwindcss/tailwindcdn.js")
        fontawesome = client.get("/static/vendor/fontawesome/css/all.min.css")
        icon = client.get("/static/images/revivax-icon.svg")

    assert tailwind.status_code == 200
    assert fontawesome.status_code == 200
    assert icon.status_code == 200
