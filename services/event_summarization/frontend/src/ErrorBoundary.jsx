import { Component } from "react";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          padding: "40px",
          fontFamily: "monospace",
          background: "#0e1b23",
          color: "#e05a5a",
          minHeight: "100vh",
        }}>
          <div style={{ color: "#e8763c", marginBottom: 12, fontSize: 13 }}>
            REACT CRASH — copy this and send it over
          </div>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, color: "#edf3f5" }}>
            {this.state.error.toString()}
            {"\n\n"}
            {this.state.error.stack}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}
