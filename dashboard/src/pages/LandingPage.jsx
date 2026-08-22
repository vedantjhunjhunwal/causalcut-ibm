import React from "react";
import "./LandingPage.css";

/**
 * LandingPage — embeds the static HTML/CSS/JS landing page via an iframe
 * served from /landing/index.html (in dashboard/public/landing/).
 *
 * Navigation from the landing page (Sign In / Get Started) uses
 * window.top.location to break out of the iframe and use the React router.
 */
export default function LandingPage() {
  return (
    <div className="landing-frame-root">
      <iframe
        src="/landing/index.html"
        className="landing-iframe"
        title="CAUSALCUT Landing Page"
        frameBorder="0"
        allowFullScreen
      />
    </div>
  );
}
