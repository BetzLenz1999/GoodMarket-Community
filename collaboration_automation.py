import logging
from datetime import datetime
import re

logger = logging.getLogger(__name__)


def _scrape_url_to_html(url: str) -> str:
    """Best-effort URL scraper used for collaboration module auto-content."""
    if not url:
        return ""
    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        response = requests.get(url, timeout=15, headers=headers, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')
        for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']):
            element.decompose()

        root = (
            soup.find('article')
            or soup.find('main')
            or soup.find('div', class_='content')
            or soup.find('body')
        )
        if not root:
            return ""

        chunks = []
        for element in root.find_all(['h1', 'h2', 'h3', 'p', 'li']):
            text = element.get_text(' ', strip=True)
            if not text:
                continue
            if element.name == 'h1':
                chunks.append(f"<h2>{text}</h2>")
            elif element.name in ('h2', 'h3'):
                chunks.append(f"<h3>{text}</h3>")
            elif element.name == 'li':
                chunks.append(f"<li>{text}</li>")
            else:
                chunks.append(f"<p>{text}</p>")
            if len(chunks) >= 80:
                break

        return "\n".join(chunks).strip()
    except Exception as exc:
        logger.warning(f"⚠️ Collaboration auto-scrape failed for {url}: {exc}")
        return ""


def _plain_text_from_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _wrap_platform_content(title: str, url: str, scraped_html: str) -> str:
    """Create a learner-friendly module body from scraped source content."""
    plain = _plain_text_from_html(scraped_html)
    if not plain:
        return ""

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', plain) if s.strip()]
    summary = " ".join(sentences[:3])[:900]

    highlights = []
    for sentence in sentences:
        clean = sentence.strip()
        if len(clean) >= 40:
            highlights.append(clean[:180])
        if len(highlights) == 4:
            break

    highlights_html = "".join([f"<li>{h}</li>" for h in highlights])
    source_label = url or "Partner provided source"

    return (
        f"<h2>{title or 'Platform Overview'}</h2>"
        f"<p>{summary or plain[:900]}</p>"
        f"<h3>Key Platform Features</h3>"
        f"<ul>{highlights_html}</ul>"
        f"<h3>Why This Matters for Learners</h3>"
        f"<p>This module was generated from the collaborator source so users can learn core platform "
        f"capabilities before taking quiz questions.</p>"
        f"<p><strong>Source:</strong> {source_label}</p>"
    )


def generate_collaboration_quiz_draft(supabase, submission_id: str, question_count: int = 15) -> int:
    modules = supabase.table('collaboration_modules') \
        .select('*') \
        .eq('submission_id', submission_id) \
        .eq('is_deleted', False) \
        .eq('is_active', True) \
        .order('display_order', desc=False) \
        .execute()
    module_rows = modules.data or []
    if not module_rows:
        return 0

    supabase.table('collaboration_quiz_questions_draft').delete().eq('submission_id', submission_id).execute()

    templates = [
        "Which statement best matches the module details about '{title}'?",
        "According to '{title}', what is the most accurate platform description?",
        "From the '{title}' module, which option reflects the documented feature?",
        "Which answer is consistent with what '{title}' explains?",
        "Based on '{title}', which statement aligns with the source content?",
    ]

    created = 0
    for idx in range(question_count):
        module = module_rows[idx % len(module_rows)]
        title = (module.get('title') or f"Module {idx + 1}").strip()
        content = _plain_text_from_html(module.get('content') or '')
        source_snippet = (content[:180] + '...') if len(content) > 180 else content
        if not source_snippet:
            source_snippet = f"{title} presents verified information from the collaborator platform."

        row = {
            'submission_id': submission_id,
            'question_id': f"COLLAB_{submission_id[:8]}_{idx + 1:02d}",
            'question': templates[idx % len(templates)].format(title=title)[:400],
            'answer_a': source_snippet[:1000],
            'answer_b': 'The module says the platform has no real product features.',
            'answer_c': 'The module confirms users can skip reading and still access hidden rewards.',
            'answer_d': f"The source link is unrelated to the collaborator platform ({module.get('url') or 'N/A'}).",
            'correct': 'A',
            'source_module_id': module.get('id')
        }
        supabase.table('collaboration_quiz_questions_draft').insert(row).execute()
        created += 1

    return created


def automate_collaboration_assets(supabase, submission_id: str, question_count: int = 15) -> dict:
    """Auto-build module content from URLs (if missing) and generate draft quiz questions."""
    modules = supabase.table('collaboration_modules') \
        .select('*') \
        .eq('submission_id', submission_id) \
        .eq('is_deleted', False) \
        .eq('is_active', True) \
        .order('display_order', desc=False) \
        .execute()

    module_rows = modules.data or []
    enriched = 0

    for module in module_rows:
        content = (module.get('content') or '').strip()
        url = (module.get('url') or '').strip()
        if content or not url:
            continue

        scraped_html = _scrape_url_to_html(url)
        wrapped = _wrap_platform_content(module.get('title') or 'Platform Module', url, scraped_html)
        if not wrapped:
            continue

        reading_time = max(1, round(len(_plain_text_from_html(wrapped).split()) / 200))
        supabase.table('collaboration_modules').update({
            'content': wrapped,
            'reading_time_minutes': reading_time,
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        }).eq('id', module.get('id')).eq('submission_id', submission_id).execute()
        enriched += 1

    created_questions = generate_collaboration_quiz_draft(supabase, submission_id, question_count=question_count)
    return {
        'modules_total': len(module_rows),
        'modules_enriched': enriched,
        'draft_questions_created': created_questions
    }
