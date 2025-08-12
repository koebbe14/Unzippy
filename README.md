# UnZippy

## Overview

UnZippy is a standalone Windows executable application (.exe) built with Python, PyQt5, and packaged using PyInstaller. It is designed to extract archives (ZIP and 7Z formats) from a specified input folder or a single archive file, recursively handling nested archives within the extracted contents while maintaining the original folder structure and naming conventions. The program creates a dedicated output folder for each top-level archive, named after the archive file (without extension), and extracts nested archives into subfolders similarly named after them.

Key features include:
- Support for password-protected archives (applied globally to all archives).
- Option to delete nested archives after successful extraction (top-level archives are not deleted).
- Logging of the extraction process to a file and on-screen display.
- Handling of multiple top-level archives if the input is a folder (searches recursively through subfolders for archives).

**Note:** While the program searches for files with extensions `.zip`, `.7z`, `.rar`, and `.tar`, it only supports extraction for `.zip` and `.7z` files. RAR and TAR files will be detected but may fail to extract, resulting in a warning in the logs. 
The application runs in a multi-threaded manner to keep the GUI responsive during extraction and is distributed as a standalone `.exe`, eliminating the need for users to install Python or dependencies.

## Requirements

- **Operating System:** Windows (the `.exe` is built for Windows; for other platforms, use the source code with Python).
- **No Additional Software Needed:** The `.exe` includes Python, PyQt5, py7zr, and all necessary libraries.
- **Permissions:** Write access to the output directory and read access to the input folder/archive.

## Installation

1. **Download the Executable:** Obtain the `UnZippy.exe` file from the distribution source (e.g., a provided download link or packaged by the developer).
2. **Place the Executable:** Save `UnZippy.exe` in a convenient directory (e.g., `C:\Users\YourName\UnZippy`).
3. **Run the Program:** Double-click `UnZippy.exe` to launch the GUI. No installation or additional software is required.

## Running the Program

1. **Launch the Application:**
   - Double-click `UnZippy.exe` in Windows Explorer.
   - Alternatively, open a Command Prompt, navigate to the directory containing the `.exe`, and run:

2.  **Selecting Input Folder or Archive**
- Select “Browse” and navigate to the location of the folder(s) to be unzipped

3. **Selecting Output Directory**
- Select “Browse” and choose a location for the unzipped folders
4. **Selecting the “delete nested archives after extraction” will delete the zipped/archived folders leaving only the unzipped folders in the Output Directory

5. **Password**
- If zip/archive file is password protected, input the password in the password field

6. **Log File Option**
- To enable a log file, select “browse” and choose an output location

7. **Extract files**
-  Click “Extract” to start the unzip process
