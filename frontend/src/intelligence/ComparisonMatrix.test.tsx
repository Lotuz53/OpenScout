import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import ComparisonMatrix from './ComparisonMatrix';

const unknownFeatureRow = {
  dimension: 'enterprise_sso',
  cells: {
    'langgenius/dify': {
      status: 'unknown' as const,
      display_label: '尚未确认',
      first_evidence_date: null,
      community_signal_count: 0,
      evidence_ids: [],
      coverage_warning: '当前时间窗口没有足够证据。',
    },
  },
};

describe('comparison matrix', () => {
  it('renders unsupported comparison cells as 尚未确认', () => {
    const markup = renderToStaticMarkup(
      <ComparisonMatrix rows={[unknownFeatureRow]} />,
    );

    expect(markup).toContain('尚未确认');
    expect(markup).toContain('当前时间窗口没有足够证据。');
  });
});
