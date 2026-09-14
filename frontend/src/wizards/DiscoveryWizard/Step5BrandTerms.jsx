export default function Step5BrandTerms({ w, patch }) {
  const t = w.termSuggestions

  function toggle(field, value, checked) {
    const next = new Set(w[field])
    if (checked) next.add(value); else next.delete(value)
    patch({ [field]: next })
  }

  if (!t || (!t.variants?.length && !t.brands?.length)) {
    return <p className="muted">No additional variants/brands suggested — you can add
      competitors later from the Source plan tab.</p>
  }

  return (
    <>
      {!!t.variants?.length && (
        <>
          <p>Product variants / real search terms to also track:</p>
          <div className="pick-list">
            {t.variants.map((v) => (
              <label className="pick-row" key={v}>
                <input type="checkbox" checked={w.selectedVariants.has(v)}
                  onChange={(e) => toggle('selectedVariants', v, e.target.checked)} />
                <div className="pick-main"><div className="pick-name">{v}</div></div>
              </label>
            ))}
          </div>
        </>
      )}
      {!!t.brands?.length && (
        <>
          <p>Real competitor brands found:</p>
          <div className="pick-list">
            {t.brands.map((b) => (
              <label className="pick-row" key={b}>
                <input type="checkbox" checked={w.selectedBrands.has(b)}
                  onChange={(e) => toggle('selectedBrands', b, e.target.checked)} />
                <div className="pick-main"><div className="pick-name">{b}</div></div>
              </label>
            ))}
          </div>
        </>
      )}
    </>
  )
}

// Nothing to fetch — step 6 is the review/launch screen.
export async function advanceFrom5() {}
