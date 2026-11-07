import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { Layout } from "@/app/Layout";

export function App() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1 } } }));
  return (
    <QueryClientProvider client={client}>
      <Layout />
    </QueryClientProvider>
  );
}
