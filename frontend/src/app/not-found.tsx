import Link from "next/link";

export default function NotFound() {
  return (
    <div className="grid min-h-screen place-items-center p-4 text-sm">
      <div>
        <p className="font-medium">Page not found</p>
        <Link href="/" className="text-accent underline">Go to the dashboard</Link>
      </div>
    </div>
  );
}
