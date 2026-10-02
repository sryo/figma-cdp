// Lumen UI components. Class names map to components.css; every prop below is a design
// property (variant axis or content), not behavior.

export function Button({ variant = "primary", disabled = false, label }) {
  // variant: "primary" | "secondary"; disabled: true | false
  return (
    <button className={`button button--${variant}`} disabled={disabled}>
      {label}
    </button>
  );
}

export function Input({ label, placeholder, type = "text" }) {
  return (
    <label className="input">
      <span className="input__label">{label}</span>
      <input className="input__field" type={type} placeholder={placeholder} />
    </label>
  );
}

export function Toggle({ on }) {
  return (
    <div className={`toggle toggle--${on ? "on" : "off"}`} role="switch" aria-checked={on}>
      <span className="toggle__knob" />
    </div>
  );
}

export function SettingsRow({ label, hint, on }) {
  return (
    <div className="settings-row">
      <div className="settings-row__text">
        <span className="settings-row__label">{label}</span>
        <span className="settings-row__hint">{hint}</span>
      </div>
      <Toggle on={on} />
    </div>
  );
}

export function ProductCard({ title, price, soldOut = false }) {
  return (
    <article className="card">
      <div className="card__image" />
      <span className="card__title">{title}</span>
      <span className="card__price">{price}</span>
      <Button variant="primary" disabled={soldOut} label={soldOut ? "Sold out" : "Add to cart"} />
    </article>
  );
}

export function Header({ links, active, cartCount }) {
  return (
    <header className="header">
      <span className="header__brand">Lumen</span>
      <nav className="header__nav">
        {links.map((l) => (
          <a key={l} className={`header__link${l === active ? " header__link--active" : ""}`}>{l}</a>
        ))}
      </nav>
      <span className="header__cart" aria-label="Cart">
        🛒<span className="header__badge">{cartCount}</span>
      </span>
    </header>
  );
}
