#!/usr/bin/env python3
"""
LUNARA local SPICE bridge.

Serves the LUNARA HTML and exposes:
  GET /api/status
  GET /api/ephemeris?start_utc=YYYY-MM-DDTHH:MM&duration_hours=24&step_minutes=15

Vectors are geometric SPICE positions of SUN and EARTH relative to MOON,
expressed in IAU_MOON, in km. The JSON schema is the one consumed by LUNARA's
existing normalizeDataset() function.

This is a local development/demo server. It binds to 127.0.0.1 by default.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

J2000_UTC = dt.datetime(2000, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
FRAME = "IAU_MOON"
OBSERVER = "MOON"
ABERRATION = "NONE"

KERNEL_URLS = {
    "naif0012.tls": "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls",
    "pck00011.tpc": "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00011.tpc",
}
EPHEMERIS_CHOICES = (
    ("de442s.bsp", "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de442s.bsp"),
    ("de440s.bsp", "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp"),
)


class SpiceUnavailable(RuntimeError):
    pass


class SpiceEngine:
    def __init__(self, kernel_dir: Path, allow_download: bool = False):
        self.kernel_dir = kernel_dir.resolve()
        self.allow_download = allow_download
        self.spice = None
        self.kernel_paths: list[Path] = []
        self.ephemeris_kernel_name: str | None = None
        self.radii_km: list[float] | None = None
        self.error: str | None = None
        self.loaded_at: str | None = None
        self._load()

    def _download(self, filename: str, url: str) -> Path:
        self.kernel_dir.mkdir(parents=True, exist_ok=True)
        target = self.kernel_dir / filename
        temporary = target.with_suffix(target.suffix + ".part")
        print(f"[LUNARA] Downloading {filename} from NAIF...")
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            if temporary.stat().st_size < 1000:
                raise RuntimeError(f"Downloaded file {filename} is unexpectedly small.")
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        return target

    def _load(self) -> None:
        try:
            import spiceypy as spice
            self.spice = spice
            self.kernel_dir.mkdir(parents=True, exist_ok=True)

            found: dict[str, Path] = {}
            missing = []
            for filename, url in KERNEL_URLS.items():
                path = self.kernel_dir / filename
                if path.is_file() and path.stat().st_size > 1000:
                    found[filename] = path
                elif self.allow_download:
                    found[filename] = self._download(filename, url)
                else:
                    missing.append(filename)

            # Prefer the current DE442s generic planetary ephemeris; accept DE440s
            # as a compatible fallback so users can reuse the kernel they already have.
            ephemeris_choice = None
            for filename, url in EPHEMERIS_CHOICES:
                path = self.kernel_dir / filename
                if path.is_file() and path.stat().st_size > 1000:
                    ephemeris_choice = (filename, path)
                    break
            if ephemeris_choice is None and self.allow_download:
                filename, url = EPHEMERIS_CHOICES[0]
                ephemeris_choice = (filename, self._download(filename, url))
            if ephemeris_choice is None:
                missing.append("de442s.bsp (preferred) or de440s.bsp")

            if missing:
                raise SpiceUnavailable(
                    "Missing kernels in "
                    + str(self.kernel_dir)
                    + ": "
                    + ", ".join(missing)
                    + ". Put the files in the kernels folder or launch with --download-missing."
                )

            ephemeris_name, ephemeris_path = ephemeris_choice
            self.ephemeris_kernel_name = ephemeris_name

            # Load time conversion, lunar constants/orientation, then planetary ephemeris.
            for path in (
                found["naif0012.tls"],
                found["pck00011.tpc"],
                ephemeris_path,
            ):
                spice.furnsh(str(path))
                self.kernel_paths.append(path)

            if spice.namfrm(FRAME) == 0:
                raise SpiceUnavailable(f"SPICE frame {FRAME} is not available after loading pck00011.tpc.")

            _dim, radii = spice.bodvrd("MOON", "RADII", 3)
            self.radii_km = [float(x) for x in radii[:3]]
            # A quick real query validates that the SPK and frame work together.
            et = spice.str2et("2026-01-01T00:00:00Z")
            spice.spkpos("SUN", et, FRAME, ABERRATION, OBSERVER)
            spice.spkpos("EARTH", et, FRAME, ABERRATION, OBSERVER)

            self.loaded_at = dt.datetime.now(dt.timezone.utc).isoformat()
            self.error = None
            print("[LUNARA] SPICE kernels loaded successfully.")
            for path in self.kernel_paths:
                print(f"         {path.name} ({path.stat().st_size:,} bytes)")
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            if self.spice is not None:
                try:
                    self.spice.kclear()
                except Exception:
                    pass
            self.kernel_paths = []
            self.radii_km = None
            print(f"[LUNARA] SPICE is not ready: {self.error}", file=sys.stderr)

    @property
    def ready(self) -> bool:
        return self.spice is not None and self.error is None and self.radii_km is not None

    def status(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "frame": FRAME,
            "observer": OBSERVER,
            "kernel_dir": str(self.kernel_dir),
            "kernels": [
                {"name": p.name, "bytes": p.stat().st_size}
                for p in self.kernel_paths if p.exists()
            ],
            "moon_radii_km": self.radii_km,
            "loaded_at_utc": self.loaded_at,
            "error": self.error,
            "message": (
                "SPICE ready. Real ephemeris vectors can be generated."
                if self.ready else
                "SPICE not ready. Check SpiceyPy installation and the required kernels."
            ),
        }

    @staticmethod
    def _parse_utc(value: str) -> dt.datetime:
        if not value:
            raise ValueError("start_utc is required (YYYY-MM-DDTHH:MM).")
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = dt.datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("Invalid start_utc. Use YYYY-MM-DDTHH:MM in UTC.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)

    def generate(self, start_utc: str, duration_hours: int, step_minutes: int) -> dict[str, Any]:
        if not self.ready:
            raise SpiceUnavailable(self.error or "SPICE kernels are not loaded.")

        duration_hours = int(duration_hours)
        step_minutes = int(step_minutes)
        if duration_hours not in (24, 48, 72):
            raise ValueError("duration_hours must be 24, 48 or 72.")
        if step_minutes not in (10, 15, 30, 60):
            raise ValueError("step_minutes must be 10, 15, 30 or 60.")

        start = self._parse_utc(start_utc)
        total_seconds = duration_hours * 3600
        step_seconds = step_minutes * 60
        offsets = list(range(0, total_seconds, step_seconds))
        if not offsets or offsets[-1] != total_seconds:
            offsets.append(total_seconds)

        samples = []
        for offset in offsets:
            instant = start + dt.timedelta(seconds=offset)
            # NAIF STR2ET converts UTC to SPICE ET/TDB using the loaded LSK.
            spice_time = instant.strftime("%Y-%m-%dT%H:%M:%SZ")
            et = float(self.spice.str2et(spice_time))

            # Geometric positions, no light-time/stellar-aberration correction.
            # This matches LUNARA's existing geometric horizon/visibility model.
            sun_pos, _ = self.spice.spkpos("SUN", et, FRAME, ABERRATION, OBSERVER)
            earth_pos, _ = self.spice.spkpos("EARTH", et, FRAME, ABERRATION, OBSERVER)

            t_utc_s = (instant - J2000_UTC).total_seconds()
            samples.append({
                "t_utc_s": t_utc_s,
                "sun": [float(v) for v in sun_pos],
                "earth": [float(v) for v in earth_pos],
            })

        return {
            "meta": {
                "source": "NASA/JPL NAIF SPICE",
                "ephemeris_kernel": self.ephemeris_kernel_name,
                "time_kernel": "naif0012.tls",
                "orientation_constants_kernel": "pck00011.tpc",
                "frame": FRAME,
                "observer": OBSERVER,
                "targets": ["SUN", "EARTH"],
                "units": "km",
                "aberration_correction": ABERRATION,
                "time_input": "UTC; converted to SPICE ET/TDB using LSK",
                "moon_radii_km": self.radii_km,
                "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "coverage_start_utc": start.isoformat(),
                "coverage_end_utc": (start + dt.timedelta(seconds=total_seconds)).isoformat(),
                "step_minutes": step_minutes,
                "sample_count": len(samples),
                "model_note": (
                    "Real DE440s ephemeris vectors in IAU_MOON. The front-end uses "
                    "the standard text-PCK lunar orientation model; this is suitable "
                    "for visualization/prototyping, not high-accuracy landing certification."
                ),
            },
            "samples": samples,
        }


class LUNARAHandler(BaseHTTPRequestHandler):
    server_version = "LUNARA-SPICE/1.1"

    def _headers(self, status: int, content_type: str, length: int):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send(self, status: int, payload: bytes, content_type: str):
        self._headers(status, content_type, len(payload))
        self.wfile.write(payload)

    def _json(self, status: int, data: dict[str, Any]):
        self._send(
            status,
            json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def do_OPTIONS(self):
        self._headers(204, "text/plain; charset=utf-8", 0)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/status":
            self._json(200, self.server.engine.status())
            return

        if parsed.path == "/api/ephemeris":
            if not self.server.engine.ready:
                self._json(503, {
                    "error": "SPICE backend is not ready.",
                    "details": self.server.engine.error,
                    "status": self.server.engine.status(),
                })
                return
            query = urllib.parse.parse_qs(parsed.query)
            try:
                start = query.get("start_utc", [""])[0]
                duration = int(query.get("duration_hours", ["24"])[0])
                step = int(query.get("step_minutes", ["15"])[0])
                data = self.server.engine.generate(start, duration, step)
                self._json(200, data)
            except (ValueError, SpiceUnavailable) as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:
                self._json(500, {
                    "error": "SPICE calculation failed.",
                    "details": f"{type(exc).__name__}: {exc}",
                })
            return

        # Serve the original HTML and its local assets (models/, images, etc.).
        try:
            raw_path = urllib.parse.unquote(parsed.path).lstrip("/")
            if not raw_path or raw_path == "":
                file_path = self.server.html_path
            else:
                file_path = (self.server.root_dir / raw_path).resolve()
                if self.server.root_dir not in file_path.parents and file_path != self.server.root_dir:
                    self._json(403, {"error": "Forbidden path."})
                    return
            if file_path.is_dir():
                file_path = file_path / "index.html"
            if not file_path.is_file():
                self._json(404, {"error": "File not found.", "path": raw_path})
                return
            content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            self._send(200, file_path.read_bytes(), content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        except Exception as exc:
            self._json(500, {"error": f"Could not serve file: {exc}"})

    def log_message(self, fmt: str, *args):
        print("[HTTP]", fmt % args)


class LUNARAServer(HTTPServer):
    def __init__(self, address, handler, engine, root_dir: Path, html_path: Path):
        super().__init__(address, handler)
        self.engine = engine
        self.root_dir = root_dir.resolve()
        self.html_path = html_path.resolve()


def main():
    parser = argparse.ArgumentParser(description="Run the LUNARA local SPICE bridge.")
    parser.add_argument("--host", default="127.0.0.1", help="Local host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port (default: 8765).")
    parser.add_argument("--kernel-dir", default="kernels", help="Folder containing DE440s, LSK and PCK kernels.")
    parser.add_argument("--html", default="index.html", help="LUNARA HTML file served at http://127.0.0.1:8765/.")
    parser.add_argument("--download-missing", action="store_true", help="Download missing generic kernels from the official NAIF server.")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parent
    kernel_dir = Path(args.kernel_dir)
    if not kernel_dir.is_absolute():
        kernel_dir = root_dir / kernel_dir
    html_path = Path(args.html)
    if not html_path.is_absolute():
        html_path = root_dir / html_path
    if not html_path.is_file():
        raise SystemExit(f"HTML file not found: {html_path}")

    engine = SpiceEngine(kernel_dir, allow_download=args.download_missing)
    if not engine.ready:
        print("\n[LUNARA] The page will still open in demo mode until SPICE is ready.")
        print("[LUNARA] Fix the message above, then restart this server.\n")

    server = LUNARAServer((args.host, args.port), LUNARAHandler, engine, root_dir, html_path)
    url = f"http://{args.host}:{args.port}/"
    print(f"\n[LUNARA] Open this address in your browser: {url}")
    print("[LUNARA] Keep this terminal open while using the application. Press Ctrl+C to stop.\n")
    try:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[LUNARA] Stopping local server...")
    finally:
        server.server_close()
        if engine.spice is not None:
            try:
                engine.spice.kclear()
            except Exception:
                pass


if __name__ == "__main__":
    main()
