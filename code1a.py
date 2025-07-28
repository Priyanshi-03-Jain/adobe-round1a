import fitz
import os
import json
import re
import string
from collections import defaultdict
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0

IN = "/app/input"
OUT = "/app/output"

MIN_FONT_SIZE = 7.0
TITLE_MAX_WORDS_EN = 35
TITLE_MAX_CHARS_JP = 100
HEADING_MAX_WORDS_EN = 20
HEADING_MAX_CHARS_JP = 70

def is_japanese(text):
    return any('\u3040' <= ch <= '\u30ff' or '\u4e00' <= ch <= '\u9faf' for ch in text)

def lang_ok(text):
    try:
        return detect(text) in {"en", "ja"}
    except:
        return True

def normalize(text):
    return re.sub(r"[^\S\r\n]+", " ", text.strip())

def is_heading_text_valid(text, is_bold, font_size, base_font_size):
    text = normalize(text)
    if len(text) < 2 or not lang_ok(text):
        return False
    if re.match(r'^\(?[a-z]', text):
        return False
    if re.match(r'^(\d+(\.\d+)*)(\s+|\.|$)', text):
        if not is_bold or font_size < base_font_size * 1.05:
            return False
        if not re.match(r'^(\d+(\.\d+)*)(\.|\s+)[A-Z(])', text):
            return False
    elif not re.match(r'^[A-Z(0-9]', text):
        return False
    if "table of contents" in text.lower():
        return False
    if any(w in text.lower() for w in ["http", "@", "copyright", "page "]):
        return False
    if is_japanese(text):
        return len(text) <= HEADING_MAX_CHARS_JP
    else:
        return len(text.split()) <= HEADING_MAX_WORDS_EN

def is_title_text_valid(text):
    text = normalize(text)
    if len(text) < 3 or not lang_ok(text):
        return False
    if "table of contents" in text.lower():
        return False
    if any(w in text.lower() for w in ["http", "@", "copyright", "page "]):
        return False
    if is_japanese(text):
        return len(text) <= TITLE_MAX_CHARS_JP
    else:
        return len(text.split()) <= TITLE_MAX_WORDS_EN

def extract_title(text_blocks):
    candidates = []
    for block in text_blocks:
        all_text = []
        for line in block["lines"]:
            line_text = "".join(span["text"] for span in line["spans"])
            all_text.append(normalize(line_text))
        full_text = " ".join(all_text)
        if not is_title_text_valid(full_text):
            continue
        is_bold = any("bold" in span["font"].lower() for line in block["lines"] for span in line["spans"])
        avg_font_size = sum(span["size"] for line in block["lines"] for span in line["spans"]) / sum(len(line["spans"]) for line in block["lines"])
        score = avg_font_size + (10 if is_bold else 0)
        candidates.append((score, full_text.strip()))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]

def detect_headings(doc):
    title_text = ""
    outline = []
    base_font_size = 0
    visited_titles = set()

    for page_num, page in enumerate(doc):
        if page_num > 50:
            break
        blocks = page.get_text("dict")["blocks"]
        text_blocks = []
        for b in blocks:
            if "lines" not in b or len(b["lines"]) == 0:
                continue
            lines = []
            for line in b["lines"]:
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                avg_font = sum(s["size"] for s in spans) / len(spans)
                lines.append({"bbox": line["bbox"], "spans": spans, "avg_font": avg_font})
            if lines:
                avg_font_block = sum(l["avg_font"] for l in lines) / len(lines)
                if avg_font_block > base_font_size:
                    base_font_size = avg_font_block
                text_blocks.append({"bbox": b["bbox"], "lines": lines, "avg_font": avg_font_block})
        
        if not title_text:
            title_text = extract_title(text_blocks)
        
        for b in text_blocks:
            for l in b["lines"]:
                line_text = "".join(s["text"] for s in l["spans"])
                norm_text = normalize(line_text)
                if norm_text in visited_titles:
                    continue
                is_bold = any("bold" in s["font"].lower() for s in l["spans"])
                font_size = l["avg_font"]
                if font_size < MIN_FONT_SIZE:
                    continue
                if is_heading_text_valid(line_text, is_bold, font_size, base_font_size):
                    visited_titles.add(norm_text)
                    level = "H1" if font_size >= base_font_size * 1.3 else "H2" if font_size >= base_font_size * 1.1 else "H3"
                    outline.append({
                        "level": level,
                        "text": norm_text,
                        "page": page_num + 1
                    })
    return {"title": title_text, "outline": outline}

def extract():
    os.makedirs(OUT, exist_ok=True)
    pdf_files = [f for f in os.listdir(IN) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print("⚠ No PDF files found in input folder.")
        return
    for fname in pdf_files:
        path = os.path.join(IN, fname)
        try:
            with fitz.open(path) as doc:
                result = detect_headings(doc)
            outname = os.path.splitext(fname)[0] + ".json"
            output_path = os.path.join(OUT, outname)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=4, ensure_ascii=False)
            print(f"✅ Processed {fname} → {outname}")
        except Exception as e:
            print(f"❌ Error processing {fname}: {e}")
            outname = os.path.splitext(fname)[0] + ".json"
            output_path = os.path.join(OUT, outname)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({"title": "", "outline": []}, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    extract()
