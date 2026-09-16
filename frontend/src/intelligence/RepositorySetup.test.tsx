import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const intelligenceMocks = vi.hoisted(() => ({
  preflight: vi.fn(),
  createProject: vi.fn(),
  syncProject: vi.fn(),
}));

vi.mock('./intelligenceService', () => ({
  default: intelligenceMocks,
}));

import preferenceReducer from '../preferences/preferenceSlice';
import RepositorySetup from './RepositorySetup';
import type { IntelligenceProject, RepositoryPreflight } from './types';

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const validPreflight: RepositoryPreflight = {
  repository: 'o/r',
  default_branch: 'main',
  archived: false,
  estimated_counts: { issues: 10, releases: 2, documents: 5 },
  warnings: [],
  error_code: null,
  message: null,
};

const project: IntelligenceProject = {
  id: 'project-1',
  user_id: 'user-1',
  repository: 'o/r',
  window_start: '2025-09-14',
  window_end: '2026-09-14',
  status: 'draft',
  last_synced_at: null,
};

function createTestStore() {
  return configureStore({
    reducer: { preference: preferenceReducer },
  });
}

async function mountSetup(): Promise<{
  container: HTMLDivElement;
  root: Root;
}> {
  const container = document.createElement('div');
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <Provider store={createTestStore()}>
        <MemoryRouter initialEntries={['/intelligence/setup']}>
          <Routes>
            <Route path="/intelligence/setup" element={<RepositorySetup />} />
            <Route path="/intelligence" element={<p>产品情报概览</p>} />
          </Routes>
        </MemoryRouter>
      </Provider>,
    );
  });
  return { container, root };
}

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    'value',
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

async function submitPreflight(container: HTMLDivElement) {
  const input = container.querySelector('#repository') as HTMLInputElement;
  const form = container.querySelector('form') as HTMLFormElement;
  await act(async () => {
    setInputValue(input, 'https://github.com/o/r.git');
    form.dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    );
    await Promise.resolve();
  });
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('repository setup', () => {
  it('preflights a repository and shows normalized estimates', async () => {
    intelligenceMocks.preflight.mockResolvedValue(validPreflight);
    const { container, root } = await mountSetup();

    await submitPreflight(container);

    expect(intelligenceMocks.preflight).toHaveBeenCalledWith(
      'https://github.com/o/r.git',
      null,
    );
    expect(container.textContent).toContain('o/r');
    expect(container.textContent).toContain('10');
    expect(container.textContent).toContain('可索引文档');

    root.unmount();
  });

  it('keeps invalid repositories from creating a project', async () => {
    intelligenceMocks.preflight.mockResolvedValue({
      ...validPreflight,
      repository: '',
      error_code: 'private_not_supported',
      message: null,
    });
    const { container, root } = await mountSetup();

    await submitPreflight(container);

    expect(container.textContent).toContain('当前阶段只支持公开 GitHub 仓库');
    expect(container.textContent).not.toContain('创建项目并开始同步');

    root.unmount();
  });

  it('requires warning confirmation before creating and syncing', async () => {
    intelligenceMocks.preflight.mockResolvedValue({
      ...validPreflight,
      archived: true,
      warnings: ['该仓库已归档，数据可能不会继续更新。'],
    });
    intelligenceMocks.createProject.mockResolvedValue(project);
    intelligenceMocks.syncProject.mockResolvedValue('task-1');
    const { container, root } = await mountSetup();

    await submitPreflight(container);

    const createButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent?.includes('创建项目并开始同步'),
    ) as HTMLButtonElement;
    expect(createButton.disabled).toBe(true);

    const confirmation = container.querySelector(
      'input[aria-label="确认仓库范围警告"]',
    ) as HTMLInputElement;
    await act(async () => {
      confirmation.click();
      await Promise.resolve();
    });
    expect(createButton.disabled).toBe(false);

    await act(async () => {
      createButton.click();
      await Promise.resolve();
    });

    expect(intelligenceMocks.createProject).toHaveBeenCalledWith({
      repository: 'o/r',
      window_start: '2025-09-14',
      window_end: '2026-09-14',
      token: null,
    });
    expect(intelligenceMocks.syncProject).toHaveBeenCalledWith(
      'project-1',
      null,
    );
    expect(container.textContent).toContain('产品情报概览');

    root.unmount();
  });
});
