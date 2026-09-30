# PDF Toolkit - Target Size Compressor

A local Flask web application that looks like a simple online PDF compressor.

## Features

- Select PDF
- Drag & drop PDF
- Target size in KB or MB
- Attempts to preserve selectable text/vector content first
- Falls back to page-image compression when needed
- Displays original and compressed sizes
- Automatically downloads the compressed PDF
- 50 MB upload limit
- Temporary files are automatically cleaned after about one hour

## 1. Create virtual environment

Windows PowerShell:

```powershell
cd D:\Python_Working\PDF_Toolkit

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 2. Install packages

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Start

```powershell
python app.py
```

Open:

http://127.0.0.1:5000

## Important compression behavior

The program first tries to recompress embedded images while keeping the PDF's text/vector content.

If the target cannot be reached, it uses a page-rasterization fallback. That can make the PDF much smaller, but text in that fallback PDF is image-based and therefore may not be selectable/searchable.

For a production server, add authentication, HTTPS, stronger upload validation, rate limiting, per-user storage isolation, and a background job queue.
