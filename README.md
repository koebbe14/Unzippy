# UnZippy 2.0

A Windows desktop tool for extracting nested ZIP and 7Z archives, built for law enforcement professionals who process electronic records received via legal process (search warrants, subpoenas, court orders). UnZippy automates the tedious work of unpacking multi-layered archive productions and optionally verifies file integrity using the SHA-512 hash values provided in Google's cover letters.

![Windows](https://img.shields.io/badge/platform-Windows%2010%2B-blue)
![Version](https://img.shields.io/badge/version-2.0-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## Features

- **Nested Archive Extraction** — Automatically detects and extracts archives within archives, recursively, until all contents are fully unpacked. Supports `.zip` and `.7z` formats.
- **Google Letter Hash Verification** — Import the cover letter PDF received from Google with responsive records. UnZippy parses "Attachment A: Hash Values for Production Files," computes SHA-512 hashes of each extracted file, and compares them against the values provided by Google to verify file integrity.
- **Password Support** — Enter a single password to decrypt encrypted archives (applied to all top-level and nested archives).
- **Optional Cleanup** — Delete intermediate nested archive files after extraction, leaving only the final unzipped content. Original input files are never modified.
- **Drag and Drop** — Drag folders, archive files, or PDF letters directly onto the input fields from File Explorer.
- **Detailed Logging** — Optionally write a timestamped log file recording every extraction, error, and hash verification result.
- **Hash Results Export** — Saves a `hashes.csv` file with all parsed filename/hash pairs and a `hash_results.txt` summary with verification outcomes.
- **Update Checker** — Check for new releases directly from the Help menu (requires internet).
- **Standalone Executable** — No Python installation required. Download and run.

---

## Download

Download the latest `UnZippy.exe` from the [Releases](https://github.com/koebbe14/Unzippy/releases) page.

### System Requirements

| Requirement | Details |
|---|---|
| **OS** | Windows 10 or later (64-bit) |
| **RAM** | 4 GB minimum (more recommended for large productions) |
| **Disk Space** | Sufficient free space for extracted files (archives can expand significantly) |
| **Internet** | Not required (only used for optional update checks) |

---

## How to Use

### 1. Launch the Application

Double-click `UnZippy.exe`. No installation is necessary.

### 2. Select Input

Click **Browse** next to "Input Folder or Archive," or drag and drop directly onto the field.

- **Folder** — Select a folder containing one or more `.zip` / `.7z` archives. UnZippy will find and process all archives inside, including in subfolders.
- **Single File** — Select an individual `.zip` or `.7z` archive.

### 3. Select Output Directory

Click **Browse** next to "Output Directory" to choose where extracted files will be saved. Each top-level archive gets its own subfolder named after the archive (without the extension). An empty folder is recommended.

> **Tip:** When you select an input, the output directory is automatically suggested as the parent folder of your input.

### 4. (Optional) Delete Nested Archives

Check **"Delete nested zips/archives after extraction"** to remove intermediate `.zip` / `.7z` files from the output after their contents have been extracted. This keeps the output folder clean with only the final unzipped files and folders. The original input archives are never modified or deleted.

### 5. (Optional) Enter Password

If the archives are encrypted, type the password in the **"Password (if encrypted)"** field. Check **Show Password** to verify what you typed. The same password is applied to all archives (top-level and nested).

### 6. (Optional) Import Google Letter PDF for Hash Verification

Click **Browse** next to "Import Google Letter PDF to Verify Hashes," or drag and drop the PDF onto the field.

This is the cover letter provided by Google with responsive records received via legal process. The letter contains an **"Attachment A: Hash Values for Production Files"** section listing each production file and its corresponding SHA-512 hash.

When a Google letter is provided, UnZippy will:

1. Parse all filenames and SHA-512 hashes from Attachment A.
2. Save a `hashes.csv` file in the output directory with the parsed data.
3. Compute the SHA-512 hash of each nested archive after extraction.
4. Compare computed hashes against the values from the letter.
5. Display a summary popup at the end showing verified, mismatched, and not-found counts.
6. Save a `hash_results.txt` file in the output directory with full details.

> **Note:** The Google letter only contains hashes for the individual production files (the `.zip` files inside the master archive), not for the master/root archive itself.

### 7. (Optional) Select Log File

Click **Browse** next to "Log File" to create a `.log` or `.txt` file that records the full extraction process with timestamps, including successes, errors, and hash verification results.

### 8. Extract

Click **Extract**. Progress and log messages appear in the text area at the bottom of the window. The button is disabled during processing. Wait for **"Extraction process completed."**

### 9. Review Results

- Check the output directory for extracted folders.
- Review `hash_results.txt` and `hashes.csv` if hash verification was used.
- Review the log file if logging was enabled.

---

## Hash Verification Details

UnZippy's hash verification is designed specifically for Google legal process productions, which follow this format in the cover letter PDF:

```
Attachment A: Hash Values for Production Files (Google Ref. No. XXXXXXXXX)

account@gmail.com.XXXX.ServiceName.DataType_001.zip:
<SHA-512 hash split across two lines>

account@gmail.com.XXXX.ServiceName.DataType_002.zip:
<SHA-512 hash split across two lines>
```

The parser handles:

- Filenames that wrap across multiple lines in the PDF.
- Hash values split across page boundaries with letterhead headers in between.
- Google's standard letterhead, page numbers, and other non-data content.

### Interpreting Results

| Result | Meaning |
|---|---|
| **Verified** | Computed hash matches the hash in the Google letter. File integrity confirmed. |
| **Mismatch** | Computed hash does not match. The file may be corrupted or tampered with. Re-download from the provider. |
| **Not Found** | No matching hash was found in the Google letter for this filename. Expected for the root/master archive. |

---

## Menu Options

| Menu Item | Description |
|---|---|
| **Help > About** | Version info, feature summary, and repository link. |
| **Help > Check for Updates** | Checks GitHub for a newer release (requires internet). |
| **Help > User Guide** | Opens a built-in detailed user guide. |

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Extraction fails with "Password required" | Enter the correct password in the password field. |
| Extraction fails with "Unsupported archive format" | Only `.zip` and `.7z` files are supported. |
| Extraction fails with "corrupted archive" | The archive may be damaged. Verify with the original source or re-download. |
| Hash verification shows "No SHA512 hash found" for root archive | This is expected. The Google letter only lists hashes for production files inside the master archive. |
| Hash mismatch | Possible file corruption during download or transfer. Re-download the production from Google. |
| PDF parsing returns 0 hashes | Ensure the PDF has selectable/extractable text (not a scanned image). The letter must contain "Attachment A: Hash Values for Production Files." |
| Application appears frozen during large extractions | Large or deeply nested archives take time. Check the log area for progress messages. |

---

## Building from Source

If you want to build the executable yourself or modify the source code:

### Prerequisites

- Python 3.10+
- Required packages:

```bash
pip install PyQt5 py7zr pdfminer.six PyPDF2 requests pyinstaller
```

### Build

```bash
pyinstaller --onefile --windowed --icon=unzippy.ico --name=UnZippy unzippy2.0.py
```

The executable will be created in the `dist/` folder.

---

## Repository

- **Source Code:** [https://github.com/koebbe14/Unzippy](https://github.com/koebbe14/Unzippy)
- **Issues:** [https://github.com/koebbe14/Unzippy/issues](https://github.com/koebbe14/Unzippy/issues)
- **Releases:** [https://github.com/koebbe14/Unzippy/releases](https://github.com/koebbe14/Unzippy/releases)

---

## License

Permission is hereby granted to law-enforcement agencies, digital-forensic analysts, and authorized investigative personnel ("Authorized Users") to use and copy this software for the purpose of criminal investigations, evidence review, training, or internal operational use.

The following conditions apply:

Redistribution: This software may not be sold, published, or redistributed to the general public. Redistribution outside an authorized agency requires written permission from the developer.

No Warranty: This software is provided "AS IS," without warranty of any kind, express or implied, including but not limited to the warranties of accuracy, completeness, performance, non-infringement, or fitness for a particular purpose. The developer shall not be liable for any claim, damages, or other liability arising from the use of this software, including the handling of digital evidence.

Evidence Integrity: Users are responsible for maintaining forensic integrity and chain of custody when handling evidence. This software does not alter source evidence files and is intended only for analysis and review.

Modifications: Agencies and investigators may modify the software for internal purposes. Modified versions may not be publicly distributed without permission from the developer.

Logging & Privacy: Users are responsible for controlling log files and output generated during use of the software to prevent unauthorized disclosure of sensitive or personally identifiable information.

Compliance: Users agree to comply with all applicable laws, departmental policies, and legal requirements when using the software.

By using this software, the user acknowledges that they have read, understood, and agreed to the above terms.
