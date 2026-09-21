from pathlib import Path


def test_entity_rendering_stays_bounded_lazy_and_navigation_safe():
    source = Path("frontend/app.js").read_text(encoding="utf-8")

    assert "entityPageSize={scenes:25,performers:25,studios:25}" in source
    assert 'id="entityPageSize"' in source
    assert "[25,50,100].map(size" in source
    assert "entityPageSize[type]=Number(b.value)" in source
    assert "pageHead(names[type],'',pageSizePicker)" in source
    assert "${libraryFilters}${pageSizePicker}" not in source
    assert "if(view!==type)return" in source
    assert "requestIdleCallback" in source
    assert "data.has_more&&data.next_cursor" in source
    assert "loading=\"lazy\"" in source


def test_entity_page_prefetch_is_deduplicated():
    source = Path("frontend/app.js").read_text(encoding="utf-8")

    assert "entityPrefetch=new Map()" in source
    assert "if(entityPrefetch.has(url))return" in source
    assert "entityPrefetch.delete(url)" in source
