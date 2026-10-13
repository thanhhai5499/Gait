import { QueryClient } from '@tanstack/react-query'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 0,        // luôn coi data là cũ → gọi lại API mỗi lần mount
      gcTime: 0,           // không giữ cache sau khi component unmount
      refetchOnMount: true,
      refetchOnWindowFocus: false,
    },
  },
})

export default queryClient
