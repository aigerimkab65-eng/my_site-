import { Component } from "react";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    if (typeof console !== "undefined" && console.error) {
      console.error("UI crashed:", error, info?.componentStack);
    }
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: "100vh",
            display: "grid",
            placeItems: "center",
            padding: "2rem",
            fontFamily: "Georgia, 'Times New Roman', serif",
            background: "#f7f3ee",
            color: "#1c1917",
            textAlign: "center",
          }}
        >
          <div>
            <h1 style={{ fontSize: "1.5rem", marginBottom: "0.75rem" }}>
              Что-то сломалось
            </h1>
            <p style={{ marginBottom: "1.25rem", opacity: 0.8 }}>
              Обновите страницу — обычно этого достаточно.
            </p>
            <button
              type="button"
              onClick={this.handleReload}
              style={{
                border: "1px solid #1c1917",
                background: "#1c1917",
                color: "#f7f3ee",
                padding: "0.65rem 1.25rem",
                cursor: "pointer",
                font: "inherit",
              }}
            >
              Обновить
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
