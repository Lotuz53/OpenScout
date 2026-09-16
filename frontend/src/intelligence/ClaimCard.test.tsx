import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import ClaimCard from './ClaimCard';
import type { Claim, Evidence } from './types';

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const claim: Claim = {
  id: 'claim-1',
  text: 'Dify 的文档提到支持企业单点登录。',
  kind: 'fact',
  evidence_ids: ['evidence-1', 'evidence-2'],
  confidence: 'high',
};

const evidence: Evidence[] = [
  {
    id: 'evidence-1',
    record_id: 'record-1',
    repository: 'langgenius/dify',
    source_type: 'documentation',
    title: 'SSO documentation',
    excerpt: 'Enterprise SSO is available.',
    source_url: 'https://github.com/langgenius/dify/wiki/sso',
    occurred_at: '2026-01-02T00:00:00Z',
    author: null,
  },
  {
    id: 'evidence-2',
    record_id: 'record-2',
    repository: 'langgenius/dify',
    source_type: 'issue',
    title: 'SSO follow-up',
    excerpt: 'The community confirmed the behavior.',
    source_url: 'https://github.com/langgenius/dify/issues/2',
    occurred_at: '2026-02-03T00:00:00Z',
    author: 'maintainer',
  },
];

afterEach(() => {
  document.body.innerHTML = '';
});

async function mountClaimCard(): Promise<{
  container: HTMLDivElement;
  root: Root;
}> {
  const container = document.createElement('div');
  const root = createRoot(container);
  await act(async () => {
    root.render(<ClaimCard claim={claim} evidence={evidence} />);
  });
  return { container, root };
}

describe('claim card', () => {
  it('opens every claim evidence source', async () => {
    const { container, root } = await mountClaimCard();
    const evidenceButton = container.querySelector(
      'button[aria-controls="claim-1-evidence"]',
    ) as HTMLButtonElement;

    expect(evidenceButton).toBeTruthy();
    expect(evidenceButton.textContent).toContain('查看 2 条证据');
    expect(container.querySelectorAll('a')).toHaveLength(0);

    await act(async () => {
      evidenceButton.click();
    });

    expect(container.querySelectorAll('a')).toHaveLength(2);
    expect(
      Array.from(container.querySelectorAll('a')).map((link) =>
        link.getAttribute('href'),
      ),
    ).toEqual([
      'https://github.com/langgenius/dify/wiki/sso',
      'https://github.com/langgenius/dify/issues/2',
    ]);
    expect(container.textContent).toContain('事实');
    expect(container.textContent).toContain('高可信度');

    root.unmount();
  });
});
