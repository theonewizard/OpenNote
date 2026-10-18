import { Button } from "@/components/ui/button";

export function Layout() {
  return (
    <div className="flex min-h-svh flex-col">
      <div className="flex flex-1 flex-col md:flex-row">
        <nav className="flex flex-col items-start gap-2 border-b p-4 md:w-60 md:shrink-0 md:border-r md:border-b-0">
          Vaults
          <Button variant="outline" size="sm" disabled>
            New note
          </Button>
        </nav>
        <section
          aria-label="Note list"
          className="border-b p-4 md:w-80 md:shrink-0 md:border-r md:border-b-0"
        >
          Notes
        </section>
        <main className="min-w-0 flex-1 p-4">No note selected</main>
      </div>
      <footer className="border-t px-4 py-1 text-sm">Not connected</footer>
    </div>
  );
}
