from __future__ import annotations

import sys
import os
import re
import csv
import glob
import shutil
import hashlib
from datetime import datetime
from typing import Tuple, List, Dict
from collections import defaultdict

# 3rd-party libs used by the app
import py7zr
import zipfile
import requests

# GUI
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QCheckBox, QTextEdit, QFileDialog,
    QLabel, QMessageBox, QDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# --- Optional PDF extractors ---
try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text  # type: ignore
except Exception:
    pdfminer_extract_text = None
try:
    import PyPDF2  # type: ignore
except Exception:
    PyPDF2 = None

CURRENT_VERSION = '2.0'
GITHUB_REPO = 'koebbe14/Unzippy'  # adjust to your repo if different

# --- Google Letter Header/Footer “noise” lines to ignore ---
NOISE_PATTERNS = [
    r"^Google LLC$",
    r"^USLawEnforcement@google\.com$",
    r"^www\.google\.com$",
    r"1600 Amphitheatre Parkway",
    r"Mountain View, California",
    r"^Attachment A\b",
    r"^Certificate of Authenticity\b",
    r"^Re:\b",
    r"^Dear\b",
    r"^\s*\d{2}/\d{2}/\d{2}\s*$",           # dates like 07/17/24 on a line
    r"^\s*Page\s+\d+(\s+of\s+\d+)?\s*$"     # "Page 1 of N"
]
NOISE_RE = [re.compile(pat, re.IGNORECASE) for pat in NOISE_PATTERNS]

def is_noise_line(line: str) -> bool:
    return any(rx.search(line) for rx in NOISE_RE)

def looks_like_filename_fragment(line: str) -> bool:
    """
    Heuristic for production filenames: might contain email '@', path-ish separators,
    or a typical extension; allow lines with ':' too (filenames end with ':').
    """
    if "@" in line:
        return True
    if "/" in line or "\\" in line:
        return True
    if re.search(r"\.[A-Za-z0-9]{1,6}\b", line):  # .zip, .pdf, .json, etc.
        return True
    if ":" in line:
        return True
    return False

def read_pdf_text(path: str) -> str:
    """
    Extract text from a PDF using pdfminer.six if available, else PyPDF2.
    Raises RuntimeError if neither can produce text.
    """
    path = str(path)
    if pdfminer_extract_text:
        try:
            return pdfminer_extract_text(path)
        except Exception:
            pass
    if PyPDF2:
        try:
            reader = PyPDF2.PdfReader(path)
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            pass
    raise RuntimeError(
        "Failed to extract text from PDF. Install pdfminer.six (recommended) "
        "or ensure PyPDF2 is installed and the file is a valid PDF."
    )

def parse_google_letter_hashes(raw_text: str) -> List[Tuple[str, str]]:
    """
    Parse 'Attachment A: Hash Values for Production Files'.
    - Rebuilds split filenames (collect lines until we see ':').
    - Accumulates SHA-512 across subsequent lines until we have 128 hex chars.
    - Skips letterhead/page headers/footers (“noise” lines).
    Returns: list of (filename, sha512_hex_lower)
    """
    t = raw_text.replace("\r", "\n")
    lines = [ln.strip() for ln in t.split("\n")]

    # Anchor to the section if present
    start_idx = None
    for i, ln in enumerate(lines):
        if "Attachment A: Hash Values for Production Files" in ln:
            start_idx = i + 1
            break
    if start_idx is None:
        start_idx = 0

    entries: List[Tuple[str, str]] = []
    i = start_idx
    n = len(lines)

    def collect_filename(idx: int) -> Tuple[str, int]:
        parts: List[str] = []
        j = idx

        # Skip noise/blank until plausible filename fragment
        while j < n:
            ln = lines[j]
            if not ln or is_noise_line(ln):
                j += 1
                continue
            if looks_like_filename_fragment(ln):
                break
            j += 1

        # Accumulate until we see a colon, skipping interleaved noise
        while j < n:
            ln = lines[j]
            if is_noise_line(ln):
                j += 1
                continue
            parts.append(ln)
            if ":" in ln:
                joined = " ".join(parts)
                joined = re.sub(r"\s+", " ", joined).strip()
                # If any header snippet snuck to the front, trim it
                for rx in NOISE_RE:
                    joined = re.sub(rf"^\s*(?:{rx.pattern})\s*", "", joined, flags=re.IGNORECASE)
                last_colon = joined.rfind(":")
                filename = joined[:last_colon].strip()
                return filename, j + 1
            j += 1

        return "", j

    def collect_sha512(idx: int) -> Tuple[str, int]:
        j = idx
        # Seek the line that mentions SHA512 in any of these forms: SHA512, SHA-512, SHA 512
        while j < n and re.search(r"SHA\s*-?\s*512", lines[j], flags=re.IGNORECASE) is None:
            j += 1
        if j >= n:
            return "", j

        hexbuf = ""
        # Collect hex across lines until we have 128 hex characters (512 bits)
        while j < n and len(re.sub(r"[^0-9a-fA-F]", "", hexbuf)) < 128:
            candidate = lines[j]
            # Strip label “...SHA512...” and any non-hex that follows it on same line
            candidate = re.sub(r"(?i)^.*SHA\s*-?\s*512[^0-9a-fA-F]*", "", candidate)
            if not is_noise_line(candidate):
                hex_only = re.sub(r"[^0-9a-fA-F]", "", candidate)
                if hex_only:
                    hexbuf += hex_only
            j += 1

        hex_only_total = re.sub(r"[^0-9a-fA-F]", "", hexbuf).lower()
        if len(hex_only_total) >= 128:
            return hex_only_total[:128], j
        return "", j

    while i < n:
        filename, i_after_name = collect_filename(i)
        if not filename:
            break
        sha512, i_after_hash = collect_sha512(i_after_name)
        if sha512:
            entries.append((filename, sha512))
        i = i_after_hash

    return entries

# ------------------ Extraction / Verification Engine ------------------

class ExtractionThread(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    hash_summary_signal = pyqtSignal(list)

    def __init__(self, input_path, output_dir, delete_nested, log_file, password, google_letter):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.delete_nested = delete_nested
        self.log_file = log_file
        self.password = password
        self.google_letter = google_letter
        self.archive_count = 0
        self.hash_dict: Dict[str, List[str]] = defaultdict(list)  # normalized filename -> [hashes]
        self.hash_results: List[str] = []

    def compute_sha512(self, file_path: str) -> str:
        sha512 = hashlib.sha512()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                sha512.update(chunk)
        return sha512.hexdigest().lower()

    def extract_archive(self, archive_path: str, output_path: str, password: str | None) -> bool:
        """
        Try extraction with py7zr first; fall back to zipfile for .zip.
        Raises exceptions on error; caller handles logging.
        """
        try:
            with py7zr.SevenZipFile(archive_path, mode='r', password=password) as archive:
                archive.extractall(output_path)
            return True
        except py7zr.exceptions.Bad7zFile:
            # maybe it's not 7z; try zip
            if archive_path.lower().endswith('.zip'):
                try:
                    with zipfile.ZipFile(archive_path, 'r') as z:
                        # If encrypted and password provided
                        try:
                            z.extractall(output_path, pwd=password.encode('utf-8') if password else None)
                        except RuntimeError as e:
                            # “Bad password” RuntimeError is common in zipfile
                            if "password required" in str(e).lower() or "encrypted" in str(e).lower():
                                raise Exception("Password required for encrypted ZIP file")
                            raise
                    return True
                except zipfile.BadZipFile as e:
                    raise Exception(f"Failed to extract as ZIP: {e}")
            raise Exception("Unsupported archive format (not 7z or zip)")
        except py7zr.exceptions.PasswordRequired:
            raise Exception("Password required for encrypted archive")
        except py7zr.exceptions.CrcException:
            raise Exception("Incorrect password or corrupted archive")

    def _variants_for_lookup(self, base: str) -> List[str]:
        """
        Generate filename variants to improve matching robustness.
        Handles spaces/no-spaces and common “part”/“preserved” conventions.
        """
        v = set()
        b = base.lower()
        v.add(b)
        v.add(''.join(b.split()))  # remove spaces
        # normalize typical chunk/part naming
        v.add(re.sub(r'-\d+\.', '.', b))                 # foo-1.zip -> foo.zip
        v.add(re.sub(r'\.\d{3}\.', '.', b))              # foo.001.zip -> foo.zip
        v.add(re.sub(r'\.preserved_\d{3}\.', '.', b))    # foo.Preserved_001.zip -> foo.zip
        # apply same to no-space variant
        ns = ''.join(b.split())
        v.add(re.sub(r'-\d+\.', '.', ns))
        v.add(re.sub(r'\.\d{3}\.', '.', ns))
        v.add(re.sub(r'\.preserved_\d{3}\.', '.', ns))
        return list(v)

    def verify_hash(self, archive_path: str) -> None:
        basename = os.path.basename(archive_path)
        candidates = self._variants_for_lookup(basename)

        expected_hashes: List[str] = []
        for key in candidates:
            expected_hashes.extend(self.hash_dict.get(key, []))

        if expected_hashes:
            computed_hash = self.compute_sha512(archive_path)
            if computed_hash in expected_hashes:
                message = f"SHA512 hash verified for '{basename}'."
            else:
                message = (
                    f"SHA512 hash mismatch for '{basename}': "
                    f"computed {computed_hash}, expected one of {expected_hashes}"
                )
        else:
            message = f"No SHA512 hash found in PDF for '{basename}'."

        self.log_signal.emit(message)
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(message + "\n")
        self.hash_results.append(message)

    def run(self):
        try:
            # Initialize log file if specified
            if self.log_file:
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    f.write(f"Extraction log for {self.input_path}\n")
                    f.write(f"Started: {datetime.now()}\n")
                self.log_signal.emit(f"Log file initialized: {self.log_file}")

            # Validate input path
            if not os.path.exists(self.input_path):
                self.log_signal.emit(f"ERROR: Input path '{self.input_path}' does not exist.")
                return

            # Ensure output directory exists
            os.makedirs(self.output_dir, exist_ok=True)

            # --- Parse hashes from Google letter PDF and write hashes.csv ---
            if self.google_letter:
                try:
                    raw_text = read_pdf_text(self.google_letter)
                    hashes = parse_google_letter_hashes(raw_text)  # list[(filename, sha512)]
                    count = len(hashes)
                    self.log_signal.emit(f"Extracted {count} hashes from Google letter PDF.")
                    if self.log_file:
                        with open(self.log_file, 'a', encoding='utf-8') as f:
                            f.write(f"Extracted {count} hashes from Google letter PDF.\n")

                    # Fill lookup dict with normalized keys
                    for filename, hsh in hashes:
                        base = os.path.basename(filename).lower()
                        for key in self._variants_for_lookup(base):
                            self.hash_dict[key].append(hsh)

                    # Save CSV
                    csv_path = os.path.join(self.output_dir, 'hashes.csv')
                    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(['filename', 'sha512'])
                        writer.writerows(hashes)
                    self.log_signal.emit(f"Hashes saved to {csv_path}")

                    # Optional: Log each pair
                    for filename, hsh in hashes:
                        msg = f"Hash entry: '{filename}' -> {hsh}"
                        self.log_signal.emit(msg)
                        if self.log_file:
                            with open(self.log_file, 'a', encoding='utf-8') as f:
                                f.write(msg + "\n")

                except Exception as e:
                    self.log_signal.emit(f"ERROR reading Google letter PDF: {str(e)}")
                    if self.log_file:
                        with open(self.log_file, 'a', encoding='utf-8') as f:
                            f.write(f"ERROR reading Google letter PDF: {str(e)}\n")
                    self.hash_dict = defaultdict(list)

            # Determine input target(s)
            if os.path.isdir(self.input_path):
                archives = []
                for root, _, files in os.walk(self.input_path):
                    for file in files:
                        if file.lower().endswith(('.zip', '.7z')):
                            archives.append(os.path.join(root, file))
                if not archives:
                    self.log_signal.emit(f"ERROR: No .zip/.7z files found in '{self.input_path}'.")
                    return
            else:
                archives = [self.input_path]

            # Process each archive
            for archive_file in archives:
                if not os.path.exists(archive_file):
                    self.log_signal.emit(f"WARNING: Archive '{archive_file}' does not exist.")
                    continue

                # Verify hash (if available)
                self.verify_hash(archive_file)

                # Extraction destination
                main_extract_folder = os.path.join(
                    self.output_dir,
                    os.path.splitext(os.path.basename(archive_file))[0]
                )
                os.makedirs(main_extract_folder, exist_ok=True)

                # Extract top-level archive
                self.log_signal.emit(f"Extracting archive: {archive_file}")
                try:
                    self.extract_archive(archive_file, main_extract_folder, self.password)
                    self.log_signal.emit(f"Extracted '{archive_file}' to '{main_extract_folder}'")
                    if self.log_file:
                        with open(self.log_file, 'a', encoding='utf-8') as f:
                            f.write(f"Extracted '{archive_file}' to '{main_extract_folder}'\n")
                except Exception as e:
                    self.log_signal.emit(f"ERROR: Failed to extract '{archive_file}': {str(e)}")
                    if self.log_file:
                        with open(self.log_file, 'a', encoding='utf-8') as f:
                            f.write(f"ERROR: Failed to extract '{archive_file}': {str(e)}\n")
                    continue

                # Find nested archives (one level deep is common; we’ll scan until none left)
                archives_to_process = [archive_file]
                while archives_to_process:
                    current_archive = archives_to_process.pop(0)
                    current_output = main_extract_folder if current_archive == archive_file else os.path.join(
                        os.path.dirname(current_archive),
                        os.path.splitext(os.path.basename(current_archive))[0]
                    )

                    nested_archives = []
                    for ext in ('*.zip', '*.7z'):
                        nested_archives.extend(glob.glob(os.path.join(current_output, ext)))

                    for nested_archive in nested_archives:
                        # Verify hash for nested archive, too
                        self.verify_hash(nested_archive)

                        nested_output = os.path.join(
                            current_output,
                            os.path.splitext(os.path.basename(nested_archive))[0]
                        )
                        os.makedirs(nested_output, exist_ok=True)

                        self.log_signal.emit(f"Extracting nested archive: {nested_archive}")
                        try:
                            self.extract_archive(nested_archive, nested_output, self.password)
                            self.archive_count += 1
                            archives_to_process.append(nested_archive)
                            self.log_signal.emit(f"Extracted '{nested_archive}' to '{nested_output}'")
                            if self.log_file:
                                with open(self.log_file, 'a', encoding='utf-8') as f:
                                    f.write(f"Extracted '{nested_archive}' to '{nested_output}'\n")
                            if self.delete_nested:
                                os.remove(nested_archive)
                                self.log_signal.emit(f"Deleted '{nested_archive}'")
                                if self.log_file:
                                    with open(self.log_file, 'a', encoding='utf-8') as f:
                                        f.write(f"Deleted '{nested_archive}'\n")
                        except Exception as e:
                            self.log_signal.emit(f"WARNING: Failed to extract '{nested_archive}': {str(e)}")
                            if self.log_file:
                                with open(self.log_file, 'a', encoding='utf-8') as f:
                                    f.write(f"WARNING: Failed to extract '{nested_archive}': {str(e)}\n")

            # Final feedback
            self.log_signal.emit(f"Extraction complete. Processed {self.archive_count} nested archives.")
            if self.log_file:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(f"Extraction complete. Processed {self.archive_count} nested archives.\n")
                    f.write(f"Finished: {datetime.now()}\n")
            if self.google_letter:
                self.hash_summary_signal.emit(self.hash_results)

        except Exception as e:
            self.log_signal.emit(f"ERROR: {str(e)}")
        finally:
            self.finished_signal.emit()

# ------------------ GUI ------------------

class UnzipNestedGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UnZippy")
        self.setGeometry(100, 100, 700, 500)
        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout()
        main_widget.setLayout(layout)

        # Input path (folder or file)
        input_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        input_button = QPushButton("Browse")
        input_button.clicked.connect(self.browse_input)
        input_layout.addWidget(QLabel("Input Folder or Archive:"))
        input_layout.addWidget(self.input_edit)
        input_layout.addWidget(input_button)
        layout.addLayout(input_layout)

        # Output directory
        output_layout = QHBoxLayout()
        self.output_edit = QLineEdit()
        output_button = QPushButton("Browse")
        output_button.clicked.connect(self.browse_output)
        output_layout.addWidget(QLabel("Output Directory:"))
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(output_button)
        layout.addLayout(output_layout)

        # Delete nested archives
        self.delete_check = QCheckBox("Delete nested zips/archives after extraction \n (new folder will only contain unzipped folders - original zipped files remain in input directory)")
        layout.addWidget(self.delete_check)

        # Password input
        password_layout = QHBoxLayout()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.show_password_check = QCheckBox("Show Password")
        self.show_password_check.stateChanged.connect(self.toggle_password_visibility)
        password_layout.addWidget(QLabel("Password (if encrypted):"))
        password_layout.addWidget(self.password_edit)
        password_layout.addWidget(self.show_password_check)
        layout.addLayout(password_layout)

        # Google letter PDF
        google_letter_layout = QHBoxLayout()
        self.google_letter_edit = QLineEdit()
        google_letter_button = QPushButton("Browse")
        google_letter_button.clicked.connect(self.browse_google_letter)
        google_letter_layout.addWidget(QLabel("Import Google Letter PDF to Verify Hashes (Optional):"))
        google_letter_layout.addWidget(self.google_letter_edit)
        google_letter_layout.addWidget(google_letter_button)
        layout.addLayout(google_letter_layout)

        # Log file
        log_layout = QHBoxLayout()
        self.log_edit = QLineEdit()
        log_button = QPushButton("Browse")
        log_button.clicked.connect(self.browse_log)
        log_layout.addWidget(QLabel("Log File (Optional):"))
        log_layout.addWidget(self.log_edit)
        log_layout.addWidget(log_button)
        layout.addLayout(log_layout)

        # Extract button
        self.extract_button = QPushButton("Extract")
        self.extract_button.clicked.connect(self.start_extraction)
        layout.addWidget(self.extract_button)

        # Log output window
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        # Add Help menu to menu bar
        menubar = self.menuBar()
        help_menu = menubar.addMenu('Help')

        # About action
        about_action = help_menu.addAction('About')
        about_action.triggered.connect(self.show_about)

        # Check for Updates action
        update_action = help_menu.addAction('Check for Updates')
        update_action.triggered.connect(self.check_for_updates)

        # User Guide action
        user_guide_action = help_menu.addAction('User Guide')
        user_guide_action.triggered.connect(self.show_user_guide)

    def toggle_password_visibility(self, state):
        self.password_edit.setEchoMode(QLineEdit.Normal if state else QLineEdit.Password)

    def browse_input(self):
        # Let user choose folder or a single file
        directory = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if directory:
            self.input_edit.setText(directory)
            # Suggest output dir as parent
            self.output_edit.setText(os.path.dirname(directory))
        else:
            file, _ = QFileDialog.getOpenFileName(self, "Select Archive (.zip or .7z)", "", "Archives (*.zip *.7z)")
            if file:
                self.input_edit.setText(file)
                self.output_edit.setText(os.path.dirname(file))

    def browse_output(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_edit.setText(directory)

    def browse_google_letter(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Google Letter PDF to Verify Hashes", "", "PDF Files (*.pdf)")
        if file:
            self.google_letter_edit.setText(file)

    def browse_log(self):
        file, _ = QFileDialog.getSaveFileName(self, "Select Log File", "", "Log Files (*.log *.txt)")
        if file:
            self.log_edit.setText(file)

    def start_extraction(self):
        input_path = self.input_edit.text().strip()
        output_dir = self.output_edit.text().strip()
        delete_nested = self.delete_check.isChecked()
        log_file = self.log_edit.text().strip() or None
        password = self.password_edit.text() or None
        google_letter = self.google_letter_edit.text().strip() or None

        if not input_path:
            self.log_text.append("ERROR: Please select an input folder or archive.")
            return
        if not output_dir:
            self.log_text.append("ERROR: Please select an output directory.")
            return

        self.extract_button.setEnabled(False)
        self.log_text.append("Starting extraction...")

        self.thread = ExtractionThread(input_path, output_dir, delete_nested, log_file, password, google_letter)
        self.thread.log_signal.connect(self.update_log)
        self.thread.finished_signal.connect(self.extraction_finished)
        self.thread.hash_summary_signal.connect(self.show_hash_summary)
        self.thread.start()

    def update_log(self, message: str):
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def extraction_finished(self):
        self.extract_button.setEnabled(True)
        self.log_text.append("Extraction process completed.")

    def show_hash_summary(self, results: List[str]):
        mismatch = [m for m in results if 'mismatch' in m]
        not_found = [m for m in results if 'No SHA512' in m]
        verified = [m for m in results if 'verified' in m]
        summary = (
            f"Hash Verification Summary:\n"
            f"Verified: {len(verified)}\n"
            f"Mismatches: {len(mismatch)}\n"
            f"Not Found: {len(not_found)}\n"
        )
        if mismatch:
            summary += "\nMismatches:\n" + "\n".join(mismatch)
        if not_found:
            summary += "\nNot Found:\n" + "\n".join(not_found)

        if mismatch:
            QMessageBox.warning(self, "Hash Summary", summary)
        else:
            QMessageBox.information(self, "Hash Summary", summary)

        # Persist summary to output dir
        out_dir = self.output_edit.text().strip() or "."
        hash_file = os.path.join(out_dir, "hash_results.txt")
        try:
            with open(hash_file, 'w', encoding='utf-8') as f:
                f.write(summary + "\n\nFull Details:\n\n" + "\n".join(results))
        except Exception:
            pass

    # Simple release check against GitHub
    def check_for_updates(self):
        def is_newer(current: str, latest: str) -> bool:
            try:
                c = tuple(map(int, current.split('.')))
                l = tuple(map(int, latest.split('.')))
                return l > c
            except Exception:
                return False
        try:
            resp = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            latest_version = data.get('tag_name', '').lstrip('v')
            if latest_version and is_newer(CURRENT_VERSION, latest_version):
                QMessageBox.information(
                    self, "Update Available",
                    f"A new version {latest_version} is available.\nDownload from: {data.get('html_url','GitHub')}"
                )
            else:
                QMessageBox.information(self, "Up to Date", f"You are running the latest version ({CURRENT_VERSION}).")
        except Exception as e:
            QMessageBox.warning(self, "Update Check Failed", f"Could not check for updates: {e}")

    def show_about(self):
        about_text = f"""
UnZippy {CURRENT_VERSION}

A tool for extracting nested ZIP and 7Z archives, with optional features like:
- Deleting nested archives after extraction
- Password support for encrypted archives
- SHA-512 hash verification using Google letter PDFs (parses Attachment A for hashes)
- Logging extraction process

Repository: https://github.com/{GITHUB_REPO}

For issues or updates, visit the GitHub repository.
"""
        QMessageBox.about(self, "About UnZippy", about_text)

    def show_user_guide(self):
        guide_text = """UnZippy User Guide
        
Introduction

UnZippy is a tool designed to extract nested ZIP and 7Z archives, commonly encountered in data productions like those from Google or other providers. It supports password-protected archives, automatic deletion of nested archives after extraction, SHA-512 hash verification using a Google letter PDF (which parses "Attachment A: Hash Values for Production Files"), and logging of the extraction process.
This program is packaged as a standalone executable for Windows (.exe), so no Python installation is required. Simply run the .exe file to launch the GUI.
System Requirements

* Windows 10 or later (64-bit recommended).

* At least 4GB RAM (more for large archives).

* Sufficient disk space for extracted files (archives can expand significantly).

* If using hash verification, ensure the Google letter is a valid PDF with extractable text.

How to Use

1. Launch the Application: Double-click the UnZippy.exe file to open the GUI.

2. Select Input:

   * Click "Browse" next to "Input Folder or Archive".

   * Choose either:

     * A folder containing one or more .zip/.7z archives (it will process all found archives recursively).

     * A single .zip or .7z file.

   * The tool will automatically detect and extract nested archives within the selected input.

3. Select Output Directory:

   * Click "Browse" next to "Output Directory".

   * Choose a folder where extracted files will be saved. Each top-level archive will get its own subfolder (named after the archive without extension).

   * Recommendation: Choose an empty folder to avoid clutter.

4. Optional: Delete Nested Archives:

   * Check the box "Delete nested zips/archives after extraction".

   * This removes intermediate .zip/.7z files after extracting their contents, leaving only the final unzipped files/folders.

   * Note: The original input archives remain untouched in their source location.

5. Optional: Enter Password:

   * If the archives are encrypted, enter the password in the "Password (if encrypted)" field.

   * Check "Show Password" to view what you've typed.

   * The same password is applied to all archives (top-level and nested).

6. Optional: Import Google Letter PDF for Hash Verification:

   * Click "Browse" next to "Import Google Letter PDF to Verify Hashes (Optional)".

   * Select the PDF (e.g., the cover letter from Google containing hash values).

   * The tool will:

     * Parse SHA-512 hashes from "Attachment A".

     * Verify hashes for all processed archives (top-level and nested).

     * Save a hashes.csv file in the output directory with parsed hashes.

     * Display a summary popup at the end (verified, mismatches, not found).

     * Save a hash_results.txt file in the output directory with full details.

   * This helps ensure file integrity against tampering or corruption.

7. Optional: Select Log File:

   * Click "Browse" next to "Log File (Optional)".

   * Choose or create a .log or .txt file to record the extraction process (timestamps, successes, errors, hash results).

8. Start Extraction:

   * Click the "Extract" button.

   * Progress and logs will appear in the text area at the bottom.

   * The button disables during processing; wait for "Extraction process completed."

   * If errors occur (e.g., wrong password), they will be logged.

9. After Extraction:

   * Check the output directory for extracted folders.

   * Review logs or hash results if enabled.

   * If deleting nested archives, the output will be clean (no intermediate .zip/.7z files).

Menu Options

* Help > About: Shows version info, features, and repository link.

* Help > Check for Updates: Checks GitHub for newer versions.

* Help > User Guide: Displays this guide.

Troubleshooting

* Extraction Fails:

  * Wrong password: Try again with the correct one.

  * Unsupported format: Only .zip and .7z are supported.

  * Corrupted archive: The file may be damaged; verify with original source.

* Hash Verification Issues:

  * "No SHA512 hash found": The filename might not match the PDF (check for variants like spaces or part numbers).

    * The Google Letter PDF does not contain a hash value for the Root zip folder, so it is common to get No Hash Found for the main/root zip folder

  * Mismatch: Possible corruption—re-download the archive.

  * PDF parsing fails: Ensure the PDF has selectable text (not scanned)

* Performance: Large/nested archives may take time and disk space. Close other apps if needed.

* No Internet?: The tool works offline except for "Check for Updates."

* Errors in Logs: Search the error message online or report on GitHub.

Advanced Notes

* The tool processes archives recursively until no more nested ones are found.

* Hash parsing handles common Google letter formats, skipping headers/footers.

* For developers: Source code is on GitHub. Built with PyQt5, py7zr, zipfile, pdfminer.six/PyPDF2.

If you encounter bugs, submit an issue on GitHub. For questions, check the repository discussions."""
        dialog = QDialog(self)
        dialog.setWindowTitle("UnZippy User Guide")
        dialog.setGeometry(100, 100, 800, 600)
        layout = QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(guide_text)
        layout.addWidget(text_edit)
        dialog.setLayout(layout)
        dialog.exec_()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = UnzipNestedGUI()
    window.show()
    sys.exit(app.exec_())