import React, { useState, useCallback } from "react";

/**
 * LiteraturePanel — GBIF literature search powered by Meilisearch.
 * 
 * Searches 62,000 ecological papers in <50ms with typo-tolerant matching.
 * Results include title, abstract, year, and keywords.
 * "Cite in chat" injects the paper into the chat input for Emily to use.
 */
export function LiteraturePanel({ onCitePaper, isLocalEmily }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [totalHits, setTotalHits] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ hasAbstract: false, minYear: 0 });

  const doSearch = useCallback(async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);

    const body = {
      q: query,
      limit: 20,
      filter_has_abstract: filters.hasAbstract,
      min_year: filters.minYear || 0,
    };

    try {
      const resp = await fetch("/v1/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Search failed");
      }
      
      const data = await resp.json();
      if (data.success) {
        setResults(data.results || []);
        setTotalHits(data.total_hits || 0);
      } else {
        setError("No results");
      }
    } catch (e) {
      setError(e.message);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query, filters]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter") doSearch();
  };

  const handleCite = (paper) => {
    if (!onCitePaper) return;
    const ctx = `[PAPER] Title: ${paper.title}\nYear: ${paper.year}\nKeywords: ${paper.keywords}\nAbstract: ${paper.abstract}\n\nUse this paper to answer the following question:\n\n`;
    onCitePaper(ctx);
  };

  return (
    <div className="literature-panel">
      <div className="literature-header">
        <h3>
          <span role="img" aria-label="books">📚</span> GBIF Literature
        </h3>
        <p className="literature-subtitle">
          62,000 ecological papers • Instant search
        </p>
      </div>

      <div className="literature-search">
        <div className="search-input-wrap">
          <input
            type="text"
            className="literature-input"
            placeholder="Search papers (e.g., MaxEnt species distribution)..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            className="search-btn"
            onClick={doSearch}
            disabled={loading || !query.trim()}
          >
            {loading ? "..." : "🔍"}
          </button>
        </div>

        <div className="search-filters">
          <label className="filter-check">
            <input
              type="checkbox"
              checked={filters.hasAbstract}
              onChange={(e) => setFilters({ ...filters, hasAbstract: e.target.checked })}
            />
            Full abstract only
          </label>
          <select
            className="filter-year"
            value={filters.minYear}
            onChange={(e) => setFilters({ ...filters, minYear: parseInt(e.target.value) })}
          >
            <option value="0">Any year</option>
            <option value="2025">2025+</option>
            <option value="2023">2023+</option>
            <option value="2020">2020+</option>
            <option value="2018">2018+</option>
          </select>
        </div>
      </div>

      {error && <div className="literature-error">⚠️ {error}</div>}

      {totalHits > 0 && (
        <div className="literature-count">
          {totalHits.toLocaleString()} results
        </div>
      )}

      <div className="literature-results">
        {results.map((paper) => (
          <div key={paper.id} className="literature-card">
            <div className="literature-card-header">
              <span className="literature-year">{paper.year || "?"}</span>
              {paper.keywords && (
                <span className="literature-keywords">{paper.keywords}</span>
              )}
            </div>
            <h4 className="literature-title">{paper.title}</h4>
            {paper.abstract && (
              <p className="literature-abstract">
                {paper.abstract.length > 300
                  ? paper.abstract.slice(0, 300) + "..."
                  : paper.abstract}
              </p>
            )}
            <button
              className="cite-btn"
              onClick={() => handleCite(paper)}
              title="Inject this paper into the chat for Emily to use"
            >
              📎 Cite in chat
            </button>
          </div>
        ))}

        {!loading && query && results.length === 0 && !error && (
          <div className="literature-empty">
            No papers found. Try different keywords.
          </div>
        )}
      </div>
    </div>
  );
}
