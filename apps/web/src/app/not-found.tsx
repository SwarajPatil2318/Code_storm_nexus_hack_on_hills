import Link from "next/link";
export default function NotFound() {
  return (
    <div className="empty-state">
      <span className="eyebrow">404 · UNMAPPED TERRITORY</span>
      <h1>Workspace not found</h1>
      <p>This route does not exist in NEXUS.</p>
      <Link href="/" className="button button-primary">
        Back to Mission Control
      </Link>
    </div>
  );
}
