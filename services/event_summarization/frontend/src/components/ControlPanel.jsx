export default function ControlPanel({
  date, onDateChange, cachedDates, countries,
  countriesLoading, countriesError, countryCode, onCountryChange,
}) {
  const dateValid = /^\d{8}$/.test(date);

  return (
    <section className="control-panel">
      <div className="field">
        <label className="field-label" htmlFor="date-input">
          Date
        </label>
        <input
          id="date-input"
          value={date}
          onChange={(e) => onDateChange(e.target.value.replace(/[^\d]/g, ""))}
          placeholder="e.g. 20260327"
          maxLength={8}
        />
        {date && !dateValid && (
          <span className="field-hint">Enter 8 digits — year, month, day (e.g. 20260327)</span>
        )}
      </div>

      <div className="field">
        <label className="field-label" htmlFor="country-select">
          Country
        </label>
        <select
          id="country-select"
          value={countryCode}
          onChange={(e) => onCountryChange(e.target.value)}
          disabled={!dateValid || countriesLoading || countries.length === 0}
        >
          <option value="">
            {countriesLoading
              ? "Loading countries…"
              : countries.length
              ? "Select a country"
              : "Enter a date first"}
          </option>
          {countries.map((c) => (
            <option key={c.code} value={c.code}>
              {c.code} — {c.name}
            </option>
          ))}
        </select>
        {countriesError && <span className="field-hint">{countriesError}</span>}
      </div>

      {cachedDates.length > 0 && (
        <div className="field">
          <label className="field-label">Recent dates</label>
          <div className="cache-chips">
            {cachedDates.slice().reverse().map((d) => (
              <button key={d} className="cache-chip" onClick={() => onDateChange(d)} type="button">
                {d.slice(0,4)}-{d.slice(4,6)}-{d.slice(6,8)}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
