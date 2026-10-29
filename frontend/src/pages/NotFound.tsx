import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mesh-bg rounded-xl p-section text-center">
      <p className="font-display text-[clamp(64px,14vw,160px)] font-bold leading-none">404</p>
      <p className="mt-md font-display text-heading-sm font-bold uppercase">This page rage-quit.</p>
      <Button asChild variant="white" className="mt-xl"><Link to="/">Back to the feed</Link></Button>
    </div>
  );
}
