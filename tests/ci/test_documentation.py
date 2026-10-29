"""Offline documentation contracts; no services, provider requests or secret reads."""
import hashlib
import html
from pathlib import Path
import re
import struct
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ('docs/README.md', 'docs/architecture.md', 'docs/development.md',
          'docs/data-sources.md', 'docs/operations.md', 'docs/archive/README.md')
ORIGINAL_README_SHA256 = '261f8afb3c1067482c7e0e8684ecff070e05728b4f0363b75bc1e8b793e0b4b1'


def prose(text):
    """Exclude fenced examples: shell/SQL syntax is not a Markdown link."""
    lines, fence = [], None
    for line in text.splitlines():
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            kind = marker[1][0]
            if fence is None:
                fence = kind
            elif fence == kind:
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return '\n'.join(lines)


def anchors(text):
    used, result = {}, set()
    visible = prose(text)
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*\s*$', visible, re.M):
        label = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', heading)
        label = re.sub(r'<[^>]+>', '', label)
        base = re.sub(r'[^\w\s-]', '', html.unescape(label).lower()).replace(' ', '-')
        number = used.get(base, 0)
        slug = base if number == 0 else f'{base}-{number}'
        while slug in result:
            number += 1
            slug = f'{base}-{number}'
        used[base] = number + 1
        result.add(slug)
    result.update(re.findall(r'\b(?:id|name)=["\']([^"\']+)["\']', visible))
    return result


def destinations(text):
    visible = prose(text)
    pattern = r'!?\[[^\]\n]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+["\'][^"\']*["\'])?\)'
    result = [first or second for first, second in re.findall(pattern, visible)]
    result += re.findall(r'\b(?:href|src)=["\']([^"\']+)["\']', visible)
    # Existing reference-style links, if introduced, must also be audited.
    result += re.findall(r'^\s{0,3}\[[^\]]+\]:\s*<?([^\s>]+)>?', visible, re.M)
    return result


class DocumentationTests(unittest.TestCase):
    def test_bilingual_product_facts_and_guide_completeness(self):
        for name in ('README.md', 'README.ru.md', *GUIDES):
            self.assertTrue((ROOT / name).is_file(), name)
        for name, opposite in (('README.md', 'README.ru.md'), ('README.ru.md', 'README.md')):
            text = (ROOT / name).read_text(encoding='utf-8')
            for fact in ('43/106', '9/281', '68515', '39214', '107729', '34/306',
                         '120×80', '2026/27', '18090', 'VERIFIED', 'PARTIAL',
                         'fd6212d5972150e11ca0161efe0e5fa32cce4992'):
                self.assertIn(fact, text, (name, fact))
            self.assertIn(f']({opposite})', text)
            self.assertIn('docs/assets/match-pass-map.png', text)
            self.assertNotIn('## Stage ', text)
            self.assertIn('https://github.com/hudl/open-data/blob/master/LICENSE.pdf', text)
            self.assertIn('alt="StatsBomb"', text)
            for context, values in (('43/106', ['64', '68515']), ('9/281', ['34', '39214'])):
                rows = [line for line in text.splitlines() if line.startswith('|') and f'`{context}`' in line]
                self.assertEqual(len(rows), 1)
                self.assertEqual([cell.strip() for cell in rows[0].strip('|').split('|')][2:4], values)
        en = (ROOT / 'README.md').read_text(encoding='utf-8')
        ru = (ROOT / 'README.ru.md').read_text(encoding='utf-8')
        self.assertIn('2026/27 is not integrated', en.replace('**', '').replace('\n', ' '))
        self.assertIn('2026/27 ещё не интегрирован', ru.replace('**', '').replace('\n', ' '))
        self.assertIn('Pass Map is accepted at local production-like 18090', en)
        self.assertIn('Pass Map принят на локальном production-like 18090', ru)
        self.assertIn('not published or deployed at 18090', en)
        self.assertIn('не опубликована и не развёрнута на 18090', ru)

    def test_legacy_readme_is_complete_after_documented_link_retargeting(self):
        text = (ROOT / 'docs/archive/README-legacy.md').read_text(encoding='utf-8')
        self.assertIn('NOT a setup or operations guide', text)
        notice, marker, original = text.partition('<!-- legacy-content-start -->\n')
        self.assertTrue(notice and marker)
        original = original.replace('](../', '](docs/')
        self.assertEqual(hashlib.sha256(original.encode('utf-8')).hexdigest(), ORIGINAL_README_SHA256)
        self.assertEqual(len(original.splitlines()), 2674)

    def test_local_markdown_destinations_and_anchors(self):
        documents = [ROOT / 'README.md', ROOT / 'README.ru.md', *sorted((ROOT / 'docs').rglob('*.md'))]
        contents = {path.resolve(): path.read_text(encoding='utf-8') for path in documents}
        headings = {path: anchors(text) for path, text in contents.items()}
        checked = 0
        for path, text in contents.items():
            for href in destinations(text):
                url = urlsplit(html.unescape(href))
                if url.scheme or url.netloc:
                    continue
                target = (path.parent / unquote(url.path)).resolve() if url.path else path
                with self.subTest(document=str(path.relative_to(ROOT)), destination=href):
                    self.assertTrue(target.is_relative_to(ROOT), 'Local link escapes repository')
                    self.assertTrue(target.exists(), 'Missing local Markdown destination')
                    if url.fragment and target.suffix == '.md':
                        self.assertIn(unquote(url.fragment), headings[target], 'Missing Markdown anchor')
                checked += 1
        self.assertGreater(checked, 150)

    def test_new_entrypoint_code_blocks_do_not_contain_destructive_or_data_write_commands(self):
        for name in ('README.md', 'README.ru.md', 'docs/development.md'):
            text = (ROOT / name).read_text(encoding='utf-8')
            blocks = '\n'.join(re.findall(r'```[^\n]*\n(.*?)```', text, re.S))
            for forbidden in (r'docker\s+compose\b[^\n]*\bdown\b', r'\bprune\b',
                              r'--force-recreate', r'ingest_\w+\.py', r'publish_\w+\.py',
                              r'load_clickhouse\w*\.py', r's3_backup\.py\s+create',
                              r'restore_s3_offline\.py'):
                self.assertNotRegex(blocks, forbidden, name)

    def test_documentation_image_is_small_png_without_embedded_text_or_exif(self):
        payload = (ROOT / 'docs/assets/match-pass-map.png').read_bytes()
        self.assertLess(len(payload), 500_000)
        self.assertEqual(payload[:8], b'\x89PNG\r\n\x1a\n')
        width, height = struct.unpack('>II', payload[16:24])
        self.assertGreaterEqual(width, 1000)
        self.assertLessEqual(width, 1600)
        self.assertGreater(height, 500)
        provenance = (ROOT / 'docs/README.md').read_text(encoding='utf-8')
        self.assertIn(f'{width}×{height}', provenance)
        self.assertIn(f'{len(payload)} bytes', provenance)
        offset, chunks = 8, []
        while offset < len(payload):
            length = struct.unpack('>I', payload[offset:offset + 4])[0]
            chunks.append(payload[offset + 4:offset + 8])
            offset += length + 12
        self.assertEqual(offset, len(payload))
        self.assertFalse({b'tEXt', b'zTXt', b'iTXt', b'eXIf'} & set(chunks))
        self.assertEqual(chunks[-1], b'IEND')


if __name__ == '__main__':
    unittest.main()
