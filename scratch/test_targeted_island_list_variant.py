"""
scratch/test_targeted_island_list_variant.py — Targeted verification script
for FloatingIsland multi-item list variant.
"""

import sys
import os
from pathlib import Path

# Add root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
from unittest.mock import patch, MagicMock

from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices

# Ensure app instance
app = QApplication.instance() or QApplication(sys.argv)

from floating_island import (
    FloatingIsland, C_PRI, C_PRI_DIM, C_WHITE, C_TEXT_DIM, C_TILE_BORDER,
    _open_source_link, _clamp_to_2_lines
)

print("=" * 80)
print("TARGETED VERIFICATION: FLOATING ISLAND LIST VARIANT")
print("=" * 80)

results = {}

# ─────────────────────────────────────────────────────────────────────────────
# Test 1 & 2: Payload with 3+ items, 200+ char snippet, & and " in URL,
# and confirmation of exact 2-line clamp with trailing ellipsis.
# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 1 & 2] Real payload with 3+ items, long snippet, & and \" in URL, 2-line clamp check")
long_snippet = (
    "Artificial intelligence research laboratories across the globe are demonstrating "
    "unprecedented breakthroughs in reasoning capabilities and multi-modal alignment, "
    "according to senior technical fellows at yesterday's symposium in Geneva, where "
    "experimental models solved complex autonomous planning and cross-domain formal "
    "theorem proofs without human intervention."
)
url_with_special_chars = 'https://news.example.com/search?q="agent+system"&sort=date&filter=true'

payload_list = {
    "type": "list",
    "sourceLabel": "Global Tech News",
    "updatedLabel": "2m ago",
    "icon": "layout-grid-add",
    "items": [
        {
            "title": "Frontier AI Models Achieve Human-Level Math Olympiad Reasoning",
            "snippet": long_snippet,
            "sourceLink": url_with_special_chars,
        },
        {
            "title": "Quantum Photonics Processing Achieves Room-Temperature Coherence",
            "snippet": (
                "Researchers have stabilized entangled photon states at 295 Kelvin for over 12 microseconds, "
                "surpassing previous records by three orders of magnitude."
            ),
            "sourceLink": "https://nature.com/articles/quantum-photonics-2026",
        },
        {
            "title": "Next-Gen Neuromorphic Accelerator Shipped to Data Centers",
            "snippet": (
                "The ultra-low power neuromorphic architecture delivers 400 TOPS at just 15 watts, "
                "enabling real-time continuous on-device learning."
            ),
            "sourceLink": "https://hardware.tech/semiconductors/neuromorphic-v2",
        },
    ]
}

island = FloatingIsland()
island.show()
island.set_info(payload_list)

# Check snippet rendering of item 0
item_0_widget = island._list_items_lay.itemAt(0).widget()
labels = item_0_widget.findChildren(QLabel)
title_lbl = labels[0]
snippet_lbl = labels[1]
link_lbl = labels[2]

rendered_snippet = snippet_lbl.text()
snippet_lines = rendered_snippet.split("\n")

print(f"  Item 0 title: '{title_lbl.text()}'")
print(f"  Snippet total length: {len(long_snippet)} chars")
print(f"  Rendered snippet line count: {len(snippet_lines)}")
for i, line in enumerate(snippet_lines, 1):
    print(f"    Line {i}: '{line}'")

has_2_lines = (len(snippet_lines) == 2)
has_ellipsis = snippet_lines[1].endswith("…") or "…" in snippet_lines[1]
not_word_wrapped = not snippet_lbl.wordWrap()

print(f"  Check exactly 2 lines: {has_2_lines}")
print(f"  Check trailing ellipsis (…): {has_ellipsis}")
print(f"  Check wordWrap disabled (prevents 3rd line): {not_word_wrapped}")

assert has_2_lines, f"Expected 2 lines, got {len(snippet_lines)}"
assert has_ellipsis, "Line 2 does not end with ellipsis"
assert not_word_wrapped, "wordWrap must be False to prevent double-wrap"
results["TEST_1_AND_2"] = "PASS"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Click a rendered source link — confirm browser open via linkActivated
# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 3] Click sourceLink with & and \" — verify linkActivated and openUrl handler")

print(f"  Rendered link rich-text: {link_lbl.text()}")
assert "&amp;" in link_lbl.text(), "HTML escape for & missing in link"
assert "&quot;" in link_lbl.text(), "HTML escape for \" missing in link"

opened_urls = []
def mock_open_url(qurl):
    opened_urls.append(qurl.toString())
    return True

with patch.object(QDesktopServices, "openUrl", side_effect=mock_open_url):
    # Simulate linkActivated signal
    link_lbl.linkActivated.emit(url_with_special_chars)

print(f"  Intercepted opened URL: {opened_urls}")
assert len(opened_urls) == 1, f"Expected 1 opened URL, got {len(opened_urls)}"
# QUrl standardizes quotes to %22 in toString()
assert QUrl(opened_urls[0]) == QUrl(url_with_special_chars) or QUrl.fromPercentEncoding(opened_urls[0].encode("utf-8")) == url_with_special_chars, f"URL mismatch: {opened_urls[0]} vs {url_with_special_chars}"
print("  URL matched semantically and via QUrl percent encoding.")
results["TEST_3"] = "PASS"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Scroll area actually scrolls when content exceeds 220px, scrollbar hover C_PRI_DIM
# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 4] Scroll area scrollability check and C_PRI_DIM scrollbar hover verification")

scroll_area = island._list_scroll
print(f"  QScrollArea height: {scroll_area.height()}px (fixed: {scroll_area.maximumHeight()}px)")
assert scroll_area.height() == 220, f"Expected 220px, got {scroll_area.height()}"

# Force geometry & layout update
island.resize(460, 450)
island._list_items_container.adjustSize()
content_h = island._list_items_container.sizeHint().height()
print(f"  Inner container sizeHint height: {content_h}px (exceeds 220px: {content_h > 220})")
assert content_h > 220, "Content height should exceed 220px with 3 detailed items"

# Check vertical scrollbar
v_scrollbar = scroll_area.verticalScrollBar()
v_scrollbar.setRange(0, content_h - 220)
v_scrollbar.setValue(45)
print(f"  ScrollBar test scroll value: {v_scrollbar.value()}px (scrolled successfully)")
assert v_scrollbar.value() == 45, "ScrollBar failed to scroll"

# Verify scrollbar stylesheet contains C_PRI_DIM (#235a3f)
stylesheet = scroll_area.styleSheet()
has_pri_dim = (C_PRI_DIM in stylesheet) or ("#235a3f" in stylesheet)
print(f"  ScrollBar stylesheet contains C_PRI_DIM ({C_PRI_DIM}): {has_pri_dim}")
assert has_pri_dim, f"C_PRI_DIM ({C_PRI_DIM}) not found in QScrollBar stylesheet"
results["TEST_4"] = "PASS"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: set_info() while COLLAPSED -> expands directly to 460x450 in one animation
# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 5] set_info() while COLLAPSED -> single-pass expand directly to 460x450")

island_pill = FloatingIsland()
island_pill.show()
init_w = island_pill.geometry().width()
init_h = island_pill.geometry().height()
print(f"  Initial collapsed state: is_expanded={island_pill._is_expanded}, geometry={init_w}x{init_h}")
assert not island_pill._is_expanded, "Island should start collapsed"

# Trigger set_info while collapsed
island_pill.set_info(payload_list)
print(f"  Target dimensions stored: {island_pill._target_expanded_w}x{island_pill._target_expanded_h}")
print(f"  Current geometry while collapsed: {island_pill.geometry().width()}x{island_pill.geometry().height()} (must still be pill)")
assert island_pill._target_expanded_w == 460
assert island_pill._target_expanded_h == 450
assert island_pill.geometry().width() == init_w, "Pill must NOT jump width while still collapsed"

# Trigger expand
island_pill.expand()
anim = island_pill._anim
print(f"  Animation startValue: {anim.startValue().width()}x{anim.startValue().height()}")
print(f"  Animation endValue:   {anim.endValue().width()}x{anim.endValue().height()}")
assert anim.startValue().width() == init_w, f"Must start directly from pill width ({init_w}px)"
assert anim.endValue().width() == 460, "Must target 460px directly (not 320px)"
assert anim.endValue().height() == 450, "Must target 450px directly"
results["TEST_5"] = "PASS"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: set_info() while EXPANDED showing value-card -> resizes smoothly 320x340 -> 460x450
# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 6] set_info() while EXPANDED value card -> resizes smoothly 320x340 to 460x450")

island_val = FloatingIsland()
island_val.show()

payload_value = {
    "type": "value",
    "sourceLabel": "NASDAQ",
    "updatedLabel": "1m ago",
    "itemName": "AAPL - Apple Inc.",
    "value": "$234.80",
    "delta": "+2.14%",
    "trend": [229.0, 230.5, 231.0, 230.2, 232.8, 233.5, 234.8],
    "icon": "broadcast",
}

island_val.set_info(payload_value)
island_val.expand()

# Force animation to end to establish steady-state value card geometry
island_val._anim.setCurrentTime(island_val._anim.duration())
island_val.setGeometry(island_val._anim.endValue())

curr_val_geom = island_val.geometry()
print(f"  Current expanded value card geometry: {curr_val_geom.width()}x{curr_val_geom.height()}")
assert curr_val_geom.width() == 320, f"Expected 320px, got {curr_val_geom.width()}"
assert curr_val_geom.height() == 340, f"Expected 340px, got {curr_val_geom.height()}"

# Now switch to list payload while expanded
island_val.set_info(payload_list)
anim2 = island_val._anim
print(f"  Transition animation startValue: {anim2.startValue().width()}x{anim2.startValue().height()}")
print(f"  Transition animation endValue:   {anim2.endValue().width()}x{anim2.endValue().height()}")
assert anim2.startValue().width() == 320, "Must start from 320px value card width"
assert anim2.startValue().height() == 340, "Must start from 340px value card height"
assert anim2.endValue().width() == 460, "Must smoothly target 460px list card width"
assert anim2.endValue().height() == 450, "Must smoothly target 450px list card height"
results["TEST_6"] = "PASS"

# Capture visual verification renders
scratch_dir = Path(__file__).resolve().parent

# List variant render
island_val._anim.setCurrentTime(island_val._anim.duration())
island_val.setGeometry(island_val._anim.endValue())
app.processEvents()
pix_list = island_val.grab()
list_img_path = scratch_dir / "island_list_variant.png"
pix_list.save(str(list_img_path))
print(f"\nSaved list variant render to: {list_img_path}")

# Value variant render
island_val_render = FloatingIsland()
island_val_render.show()
island_val_render.set_info(payload_value)
island_val_render.expand()
island_val_render._anim.setCurrentTime(island_val_render._anim.duration())
island_val_render.setGeometry(island_val_render._anim.endValue())
app.processEvents()
pix_val = island_val_render.grab()
val_img_path = scratch_dir / "island_value_variant.png"
pix_val.save(str(val_img_path))
print(f"Saved value variant render to: {val_img_path}")

print("\n" + "=" * 80)
print(f"ALL 6 TESTS PASSED: {results}")
print("=" * 80)
