import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type { Meta, Product, Summary } from './types'
import { toast } from './components/Toaster'

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: () => api.get<Meta>('/meta'), staleTime: Infinity })
}

export function useSummary() {
  return useQuery({
    queryKey: ['summary'],
    queryFn: () => api.get<Summary>('/summary'),
    refetchInterval: 5000,
  })
}

/** Star / un-star a product; refreshes every view that shows favourites. */
export function useToggleFavorite() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: Pick<Product, 'id' | 'favorite'>) =>
      p.favorite ? api.del(`/favorites/${encodeURIComponent(p.id)}`) : api.put(`/favorites/${encodeURIComponent(p.id)}`, {}),
    onSuccess: (_d, p) => {
      toast(p.favorite ? 'Removed from favourites' : 'Added to favourites — you will be alerted on restocks & drops')
      qc.invalidateQueries({ queryKey: ['products'] })
      qc.invalidateQueries({ queryKey: ['product', p.id] })
      qc.invalidateQueries({ queryKey: ['favorites'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })
}
