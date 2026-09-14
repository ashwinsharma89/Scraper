export default function Modal({ title, onClose, className = 'wizard-card', children }) {
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className={`card ${className}`}>
        <div className="card-head"><h2>{title}</h2><button className="x" onClick={onClose}>×</button></div>
        {children}
      </div>
    </div>
  )
}
