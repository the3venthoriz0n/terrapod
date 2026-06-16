/**
 * Unit tests for workspace-grouping.ts.
 *
 * Run: cd web && npx vitest run src/lib/workspace-grouping.test.ts
 * (Requires vitest installed: npm i -D vitest)
 */

import { describe, it, expect } from 'vitest'
import {
  buildWorkspaceTree,
  countWorkspaces,
  parseGroupParam,
  serializeGroupParam,
  type GroupMode,
} from './workspace-grouping'

function ws(name: string, dir = '', repo = '') {
  return {
    id: `ws-${name}`,
    attributes: {
      name,
      'working-directory': dir,
      'vcs-repo-url': repo,
      labels: null,
    },
  }
}

describe('parseGroupParam', () => {
  it('returns flat for null', () => {
    expect(parseGroupParam(null)).toBe('flat')
  })
  it('returns flat for unknown values', () => {
    expect(parseGroupParam('unknown')).toBe('flat')
    expect(parseGroupParam('path')).toBe('flat') // old value no longer valid
  })
  it('parses repo', () => {
    expect(parseGroupParam('repo')).toBe('repo')
  })
  it('parses repo-path', () => {
    expect(parseGroupParam('repo-path')).toBe('repo-path')
  })
})

describe('serializeGroupParam', () => {
  it('returns null for flat', () => {
    expect(serializeGroupParam('flat')).toBeNull()
  })
  it('returns the mode string for non-flat', () => {
    expect(serializeGroupParam('repo')).toBe('repo')
    expect(serializeGroupParam('repo-path')).toBe('repo-path')
  })
})

describe('buildWorkspaceTree', () => {
  it('returns empty for flat mode', () => {
    const result = buildWorkspaceTree([ws('a')], 'flat')
    expect(result).toEqual([])
  })

  describe('repo mode', () => {
    it('groups VCS workspaces by repo basename', () => {
      const workspaces = [
        ws('ws-a', 'dir-a', 'https://github.com/org/repo-one'),
        ws('ws-b', 'dir-b', 'https://github.com/org/repo-one'),
        ws('ws-c', '', 'https://github.com/org/repo-two'),
      ]
      const result = buildWorkspaceTree(workspaces, 'repo')
      expect(result.length).toBe(2)
      expect(result[0].key).toBe('repo-one')
      expect(result[0].workspaces.length).toBe(2)
      expect(result[0].children.length).toBe(0) // flat within repo
      expect(result[1].key).toBe('repo-two')
      expect(result[1].workspaces.length).toBe(1)
    })

    it('groups local workspaces separately', () => {
      const workspaces = [
        ws('vcs-ws', '', 'https://github.com/org/my-repo'),
        ws('local-ws', ''),
      ]
      const result = buildWorkspaceTree(workspaces, 'repo')
      expect(result.length).toBe(2)
      expect(result[0].key).toBe('my-repo')
      expect(result[1].key).toBe('__local__')
      expect(result[1].label).toBe('Local')
    })

    it('handles SSH repo URLs', () => {
      const workspaces = [ws('ws-a', '', 'git@github.com:org/ssh-repo.git')]
      const result = buildWorkspaceTree(workspaces, 'repo')
      expect(result[0].key).toBe('ssh-repo')
    })
  })

  describe('repo-path mode', () => {
    it('creates path tree within repo groups', () => {
      const workspaces = [
        ws('ws-a', 'environments/dev', 'https://github.com/org/infra'),
        ws('ws-b', 'environments/prod', 'https://github.com/org/infra'),
        ws('ws-c', 'modules/vpc', 'https://github.com/org/infra'),
      ]
      const result = buildWorkspaceTree(workspaces, 'repo-path')
      expect(result.length).toBe(1)
      const repo = result[0]
      expect(repo.key).toBe('infra')
      expect(repo.children.length).toBe(2) // environments/, modules/
      const envGroup = repo.children.find(g => g.key === 'environments')!
      expect(envGroup.children.length).toBe(2) // dev/, prod/
      expect(envGroup.children[0].workspaces.length).toBe(1)
    })

    it('places workspaces without working-directory at repo root', () => {
      const workspaces = [
        ws('root-ws', '', 'https://github.com/org/repo'),
        ws('nested-ws', 'sub/dir', 'https://github.com/org/repo'),
      ]
      const result = buildWorkspaceTree(workspaces, 'repo-path')
      const repo = result[0]
      expect(repo.workspaces.length).toBe(1)
      expect(repo.workspaces[0].name).toBe('root-ws')
      expect(repo.children.length).toBe(1) // sub/
    })

    it('normalizes leading slashes', () => {
      const workspaces = [ws('ws-a', '/leading/slash', 'https://github.com/org/repo')]
      const result = buildWorkspaceTree(workspaces, 'repo-path')
      const repo = result[0]
      expect(repo.children[0].key).toBe('leading')
    })

    it('handles empty working-directory string', () => {
      const workspaces = [ws('ws-a', '', 'https://github.com/org/repo')]
      const result = buildWorkspaceTree(workspaces, 'repo-path')
      expect(result[0].workspaces[0].name).toBe('ws-a')
    })

    it('groups local workspaces with path expansion', () => {
      const workspaces = [
        ws('local-a', 'apps/web'),
        ws('local-b', 'apps/api'),
        ws('local-c', ''),
      ]
      const result = buildWorkspaceTree(workspaces, 'repo-path')
      expect(result.length).toBe(1) // just Local group
      const local = result[0]
      expect(local.key).toBe('__local__')
      expect(local.workspaces.length).toBe(1) // local-c at root
      expect(local.children[0].key).toBe('apps')
      expect(local.children[0].children.length).toBe(2) // web/, api/
    })

    it('handles multi-level nesting', () => {
      const workspaces = [ws('deep', 'a/b/c/d', 'https://github.com/org/repo')]
      const result = buildWorkspaceTree(workspaces, 'repo-path')
      const repo = result[0]
      expect(repo.children[0].key).toBe('a')
      expect(repo.children[0].children[0].key).toBe('b')
      expect(repo.children[0].children[0].children[0].key).toBe('c')
      expect(repo.children[0].children[0].children[0].children[0].key).toBe('d')
      expect(repo.children[0].children[0].children[0].children[0].workspaces[0].name).toBe('deep')
    })
  })
})

describe('countWorkspaces', () => {
  it('counts workspaces recursively', () => {
    const workspaces = [
      ws('a', 'x', 'https://github.com/org/repo'),
      ws('b', 'x/y', 'https://github.com/org/repo'),
      ws('c', '', 'https://github.com/org/repo'),
    ]
    const result = buildWorkspaceTree(workspaces, 'repo-path')
    expect(countWorkspaces(result[0])).toBe(3)
  })
})
