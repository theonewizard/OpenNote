export function Layout() {
  return (
    <div className="flex min-h-svh flex-col">
      <div className="flex flex-1 flex-col md:flex-row">
        <nav className="border-b p-4 md:w-60 md:shrink-0 md:border-r md:border-b-0">
          Vaults
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
