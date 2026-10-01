// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api.js', () => ({
  api: { search: vi.fn(async () => ({ results: [{ id: 'sr:mage' }] })) },
}))

const navSpy = vi.fn()
vi.mock('react-router-dom', async () => {
  const real = await vi.importActual('react-router-dom')
  return { ...real, useNavigate: () => navSpy }
})

import WikiText from './WikiText.jsx'

const wrap = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('WikiText', () => {
  it('deja el texto plano intacto', () => {
    const { container } = wrap(<WikiText text="nota sin enlaces" />)
    expect(container.textContent).toBe('nota sin enlaces')
    expect(container.querySelector('.wikilink')).toBeNull()
  })

  it('[[entidad conocida]] enlaza a su ancla', () => {
    const ents = [{ id: 'e1', name: 'Torre Gris' }]
    wrap(<WikiText text="Cerca de la [[Torre Gris]] hay goblins"
                   entities={ents} />)
    const a = screen.getByRole('link', { name: 'Torre Gris' })
    expect(a.getAttribute('href')).toBe('#ent-e1')
  })

  it('[[desconocido]] busca en el compendio y navega al resultado',
     async () => {
       wrap(<WikiText text="un [[Mago]] aparece" />)
       fireEvent.click(screen.getByRole('button', { name: 'Mago' }))
       await waitFor(() =>
         expect(navSpy).toHaveBeenCalledWith('/content/sr%3Amage'))
     })

  it('[[desconocido]] sin resultado va a /search', async () => {
    const { api } = await import('../api.js')
    api.search.mockResolvedValueOnce({ results: [] })
    wrap(<WikiText text="un [[Inventado]]" />)
    fireEvent.click(screen.getByRole('button', { name: 'Inventado' }))
    await waitFor(() =>
      expect(navSpy).toHaveBeenCalledWith('/search'))
  })
})
