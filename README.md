# Adobe Hackathon Round 1A — Understand Your Document

## 🧠 Problem
Given a PDF file, extract:
- Title
- Headings: H1, H2, H3
- Page numbers for each heading

And output a structured JSON.

---

## 🧩 My Approach

I used `PyMuPDF` (`fitz`) to:
- Read PDF text block-by-block
- Compare font sizes and styles
- Identify the title and headings (based on size, boldness, and length)
- Filter out paragraphs and irrelevant lines

Heading levels were determined by clustering font sizes into three groups:
- Largest font size → `H1`
- Medium size → `H2`
- Smallest valid heading size → `H3`

Title is assumed to be the largest, centered line on page 1.

---

## 📚 Libraries Used

- `PyMuPDF` (fitz)
- `os`, `json`, `collections`
- `re` (for simple filtering)

Everything runs **offline**, no external APIs or models used.

---

## 🐳 How to Build and Run

This project runs inside Docker as required.

### Build Image
```bash
docker build --platform linux/amd64 -t adobe-outline-extractor .
