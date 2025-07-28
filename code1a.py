import fitz
import os
import json
import re
import string
from collections import Counter, defaultdict
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0

IN = "/app/input"
OUT = "/app/output"

MIN_FONT_SIZE = 8.0
TITLE_MAX_WORDS = 30
HEADING_MAX_WORDS = 15
TOP_MARGIN_RATIO = 0.35
BOTTOM_MARGIN_PX = 80
MIN_DIFF_SIZE = 0.8
SCORE_THRESHOLD = 5.0
MERGE_Y_THRESHOLD = 10
MERGE_X_GAP = 20
MAX_DOC_PAGES = 100
MIN_WORDS_FOR_HEADING = 2

numbered_prefix_re = re.compile(r'^((\d+(\.\d+)(\s[-–—:]?|\.?))|[A-Z])(\.|\))\s+')
symbol_prefix_re = re.compile(r'^[-•·▪—–()\[\]]\s')  
url_re = re.compile(r'https?://\S+|www\.\S+|ftp\.\S+')
punctuation_end_re = re.compile(r'[.?!;,:]$')

def normalize_text(text):
    return re.sub(r'[\W_]+', '', text).lower()

def detect_language(texts):
    sample = " ".join(texts[:min(len(texts), 200)])
    if not sample.strip():
        return "en"
    try:
        return detect(sample)
    except:
        return "en"

def looks_like_table_block(text):
    if not text.strip():
        return False
    digit_punct_count = sum(c.isdigit() or c in string.punctuation for c in text)
    ratio = digit_punct_count / max(len(text), 1)
    if ratio > 0.4:
        return True
    if len(text.split()) <= 3 and any(c.isdigit() for c in text):
        return True
    if re.search(r'\d{4,}|(\d{1,3}[,.\s]\d{3})', text):
        return True
    if re.search(r'\s{2,}\S+\s{2,}\S+', text) and len(text.split()) > 2:
        return True
    return False

def contains_japanese(text):
    return bool(re.search(r'[\u3040-\u30ff\u4e00-\u9fff\uff00-\uffef]', text))

def has_link(text):
    return bool(url_re.search(text))

def is_bold(span):
    font_lower = span["font"].lower()
    return "bold" in font_lower or "heavy" in font_lower or span["flags"] & 16

def cluster_font_sizes(sizes):
    sizes = sorted([s for s in sizes if s >= MIN_FONT_SIZE], reverse=True)
    if not sizes:
        return []
    clusters = []
    current_cluster = []

    for s in sizes:
        if not current_cluster:
            current_cluster.append(s)
        elif abs(s - current_cluster[-1]) <= MIN_DIFF_SIZE:
            current_cluster.append(s)
        else:
            clusters.append(sum(current_cluster) / len(current_cluster))
            current_cluster = [s]
    if current_cluster:
        clusters.append(sum(current_cluster) / len(current_cluster))

    return sorted(clusters, reverse=True)

def get_candidate_spans(doc):
    spans = []
    text_frequency = Counter()

    for page_num, page in enumerate(doc):
        page_height = page.rect.height
        page_width = page.rect.width

        footer_area_bottom = page_height - BOTTOM_MARGIN_PX

        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if not block.get("lines"):
                continue

            block_bbox = fitz.Rect(block["bbox"])
            block_text_combined = "".join(s["text"] for line in block["lines"] for s in line["spans"]).strip()

            if looks_like_table_block(block_text_combined) or has_link(block_text_combined):
                continue

            if block_bbox.y0 < BOTTOM_MARGIN_PX or block_bbox.y1 > footer_area_bottom:
                continue

            for line in block["lines"]:
                line_bbox = fitz.Rect(line["bbox"])

                for span in line["spans"]:
                    text = span["text"].strip()
                    span_bbox = fitz.Rect(span["bbox"])

                    if not text or span["size"] < MIN_FONT_SIZE:
                        continue

                    if span_bbox.y0 < BOTTOM_MARGIN_PX or span_bbox.y1 > footer_area_bottom:
                        continue

                    if looks_like_table_block(text) or has_link(text):
                        continue

                    text_frequency[text] += 1
                    spans.append({
                        "text": text,
                        "size": round(span["size"], 1),
                        "bold": is_bold(span),
                        "page": page_num + 1,
                        "y0": span_bbox.y0,
                        "y1": span_bbox.y1,
                        "x0": span_bbox.x0,
                        "x1": span_bbox.x1,
                        "page_height": page_height,
                        "page_width": page_width,
                        "block_bbox": list(block_bbox),
                        "line_bbox": list(line_bbox)
                    })

    filtered_spans = []
    text_on_pages = defaultdict(set)
    for sp in spans:
        text_on_pages[normalize_text(sp["text"])].add(sp["page"])

    for sp in spans:
        norm_text = normalize_text(sp["text"])
        if (len(sp["text"]) <= 5 or sp["text"].isdigit()) and len(text_on_pages[norm_text]) > doc.page_count / 3:
            continue
        if text_frequency[sp["text"]] > 3 and len(sp["text"].split()) < 5:
            continue
        filtered_spans.append(sp)

    return filtered_spans

def merge_spans(spans):
    if not spans:
        return []
    spans = sorted(spans, key=lambda s: (s["page"], s["y0"], s["x0"]))
    merged = []
    current = spans[0].copy()

    for sp in spans[1:]:
        same_page = sp["page"] == current["page"]
        y_threshold_dynamic = MERGE_Y_THRESHOLD
        if abs(sp["size"] - current["size"]) < MIN_DIFF_SIZE:
             y_threshold_dynamic = MERGE_Y_THRESHOLD * 1.5

        close_vert = abs(sp["y0"] - current["y0"]) <= y_threshold_dynamic
        close_horiz = (sp["x0"] - current["x1"]) <= MERGE_X_GAP
        aligned_x = (abs(sp["x0"] - current["x0"]) < 5 or
                     sp["x0"] > current["x0"])

        if same_page and close_vert and (close_horiz or aligned_x):
            add_space = not (current["text"] and punctuation_end_re.search(current["text"])) and \
                        not (sp["text"] and sp["text"][0] in string.punctuation + "、。・「」『』（）")

            if add_space and current["text"] and sp["text"]:
                current["text"] += " "
            current["text"] += sp["text"]
            current["x1"] = max(current["x1"], sp["x1"])
            current["y1"] = max(current["y1"], sp["y1"])
            current["size"] = max(current["size"], sp["size"])
            current["bold"] = current["bold"] or sp["bold"]
        else:
            merged.append(current)
            current = sp.copy()
    merged.append(current)
    return merged

def score_span(span, clusters, lang):
    size = span["size"]
    text = span["text"].strip()
    y0 = span["y0"]
    bold = span["bold"]
    page_h = span["page_height"]
    page_w = span["page_width"]

    rank = next((i for i, c in enumerate(clusters) if abs(size - c) <= MIN_DIFF_SIZE), None)
    if rank is None:
        return 0

    score = (len(clusters) - rank) * 4

    if y0 < page_h * TOP_MARGIN_RATIO:
        score += 2.5
    center_x = (span["x0"] + span["x1"]) / 2
    page_center_x = page_w / 2
    if abs(center_x - page_center_x) < page_w * 0.2:
        score += 0.5

    if bold:
        score += 2.0

    word_count = len(text.split())
    if lang == "en":
        if text.isupper() and word_count > 1:
            score += 1.5
        elif text.istitle() and word_count > 1:
            score += 1.0
        if word_count > HEADING_MAX_WORDS:
            return 0
        if word_count < MIN_WORDS_FOR_HEADING and not bold and not numbered_prefix_re.match(text):
            return 0
    else:
        if contains_japanese(text):
            score += 2.0
        if len(text) > 50:
            return 0
        if len(text) <= 1 and not bold:
            return 0

    if numbered_prefix_re.match(text):
        score += 1.5
    if symbol_prefix_re.match(text) and lang == "en":
        if not bold or size < clusters[0]:
            score -= 2.0
            if score < 0: return 0

    if has_link(text):
        return 0
    if looks_like_table_block(text):
        return 0
    if punctuation_end_re.search(text) and not text.endswith(':'):
        return 0

    return score

def extract_title(spans, clusters, lang):
    if not clusters:
        return "", set()

    max_font_size = 0
    if spans:
        max_font_size = max(sp["size"] for sp in spans)

    if not max_font_size or max_font_size < MIN_FONT_SIZE:
        return "", set()

    title_font_cluster_avg = next((c for c in clusters if abs(max_font_size - c) <= MIN_DIFF_SIZE), clusters[0])

    candidates = []
    for i, sp in enumerate(spans):
        if sp["page"] != 1:
            continue
        if abs(sp["size"] - title_font_cluster_avg) > MIN_DIFF_SIZE * 1.5:
            continue
        if sp["y0"] > sp["page_height"] * TOP_MARGIN_RATIO:
            continue
        
        center_x = (sp["x0"] + sp["x1"]) / 2
        page_center_x = sp["page_width"] / 2
        if abs(center_x - page_center_x) > sp["page_width"] * 0.35:
            continue

        word_count = len(sp["text"].split())
        if lang == "en" and word_count > TITLE_MAX_WORDS:
            continue
        if lang != "en" and len(sp["text"]) > 60:
            continue
        if looks_like_table_block(sp["text"]) or has_link(sp["text"]):
            continue
        if punctuation_end_re.search(sp["text"]) and not sp["text"].endswith(':'):
            continue
        if sp["text"].lower().strip() in ["contents", "table of contents", "index", "references", "acknowledgements"]:
            continue

        candidates.append((i, sp))

    if not candidates:
        page1_spans = [sp for sp in spans if sp["page"] == 1]
        if page1_spans:
            scored_page1_spans = sorted(
                [(score_span(sp, clusters, lang), i, sp) for i, sp in enumerate(spans) if sp in page1_spans],
                key=lambda x: x[0], reverse=True
            )
            if scored_page1_spans and scored_page1_spans[0][0] >= SCORE_THRESHOLD * 1.5:
                best_span = scored_page1_spans[0][2]
                return best_span["text"], {scored_page1_spans[0][1]}
        return "", set()

    candidates.sort(key=lambda x: x[1]["y0"])

    grouped_lines = []
    current_group = []
    prev_y1 = None

    for idx, sp in candidates:
        if not current_group:
            current_group.append((idx, sp))
        else:
            line_height = sp["y1"] - sp["y0"]
            prev_line_height = current_group[-1][1]["y1"] - current_group[-1][1]["y0"]
            max_allowed_gap = max(line_height, prev_line_height) * 1.5

            if abs(sp["y0"] - prev_y1) <= max_allowed_gap:
                current_group.append((idx, sp))
            else:
                grouped_lines.append(current_group)
                current_group = [(idx, sp)]
        prev_y1 = sp["y1"]

    if current_group:
        grouped_lines.append(current_group)

    best_group = []
    best_score = -1
    for group in grouped_lines:
        group_text_length = sum(len(sp["text"]) for _, sp in group)
        group_avg_size = sum(sp["size"] for _, sp in group) / len(group)
        current_group_score = group_text_length + (group_avg_size * 5)

        if current_group_score > best_score:
            best_score = current_group_score
            best_group = group

    if not best_group:
        return "", set()

    title_text = " ".join(sp["text"] for _, sp in best_group).strip()
    title_text = re.sub(r'^[,\s\-–—:]+|[,\s\-–—:]+$', '', title_text).strip()

    indices = {idx for idx, _ in best_group}
    return title_text, indices

def detect_headings(doc):
    if doc.page_count > MAX_DOC_PAGES:
        return {"title": "", "outline": []}

    spans = get_candidate_spans(doc)
    merged_spans = merge_spans(spans)

    if not merged_spans:
        return {"title": "", "outline": []}

    all_sizes = [sp["size"] for sp in merged_spans]
    clusters = cluster_font_sizes(all_sizes)

    if not clusters:
        return {"title": "", "outline": []}

    lang = detect_language([sp["text"] for sp in merged_spans if sp["text"].strip()])

    title_text, title_indices = extract_title(merged_spans, clusters, lang)

    seen_normalized_texts = set()
    outline = [] # Changed to flat list as per new requirement

    heading_level_map = {}
    for i in range(min(3, len(clusters))):
        heading_level_map[round(clusters[i], 1)] = f"H{i+1}"

    for i, sp in enumerate(merged_spans):
        if i in title_indices:
            continue

        text = sp["text"].strip()
        if not text:
            continue

        score = score_span(sp, clusters, lang)
        if score < SCORE_THRESHOLD:
            continue

        normalized_key = normalize_text(text)
        if normalized_key in seen_normalized_texts:
            continue
        seen_normalized_texts.add(normalized_key)

        level_assigned = None

        for cluster_avg_size_rounded, level_str in heading_level_map.items():
            if abs(sp["size"] - cluster_avg_size_rounded) <= MIN_DIFF_SIZE:
                level_assigned = level_str
                break
        
        if level_assigned is None:
            continue

        outline.append({
            "level": level_assigned,
            "text": text,
            "page": sp["page"]
        })

    return {"title": title_text, "outline": outline}

def extract():
    os.makedirs(OUT, exist_ok=True)
    pdf_files = [f for f in os.listdir(IN) if f.lower().endswith(".pdf")]

    if not pdf_files:
        return

    for fname in pdf_files:
        path = os.path.join(IN, fname)
        doc = None
        try:
            doc = fitz.open(path)
            result = detect_headings(doc)
            doc.close()

            outname = os.path.splitext(fname)[0] + ".json"
            output_path = os.path.join(OUT, outname)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=4, ensure_ascii=False)

        except fitz.EmptyOutlineError:
            if doc:
                doc.close()
            try:
                doc = fitz.open(path)
                result = detect_headings(doc)
                doc.close()
                outname = os.path.splitext(fname)[0] + ".json"
                output_path = os.path.join(OUT, outname)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=4, ensure_ascii=False)
            except Exception:
                if doc: doc.close()

        except Exception:
            if doc: doc.close()

if __name__ == "__main__":
    extract()
