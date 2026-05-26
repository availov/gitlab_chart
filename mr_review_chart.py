import gitlab
import pandas as pd
from datetime import datetime, timedelta, timezone
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import numpy as np
from pathlib import Path
from urllib.parse import urlparse
import argparse


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def extract_project_slug(web_url: str) -> str:
    parsed = urlparse(web_url)
    path = parsed.path
    if '/-/' in path:
        return path.split('/-/')[0].strip('/')

    return path.strip('/')


def main():
    parser = argparse.ArgumentParser(description='GitLab MR Review Heat Dashboard')
    parser.add_argument('--url', default='https://gitlab.com', help='GitLab URL')
    parser.add_argument('--token', required=True, help='Personal access token')
    parser.add_argument('--group', required=True, help='Group path or ID')
    parser.add_argument(
        '--days', type=int, default=0,
        help='Look back N days for open MRs (0 = all open MRs)',
    )
    parser.add_argument('--top-n', type=int, default=15, help='Rows in hot/cold MR panels')
    parser.add_argument('--top-authors', type=int, default=25, help='Rows in the review age authors chart')
    parser.add_argument('--output', default='gitlab_charts', help='Output directory')
    parser.add_argument('--include-subgroups', action='store_true', default=True)
    args = parser.parse_args()

    gl = gitlab.Gitlab(args.url, private_token=args.token, ssl_verify=True)
    group = gl.groups.get(args.group)
    print(f'Group: {group.full_name}')
    print(f'Fetching open MRs{"" if args.days == 0 else f" from last {args.days} days"}...\n')

    kwargs = dict(
        state='opened',
        per_page=100,
        iterator=True,
        include_subgroups=args.include_subgroups,
    )
    if args.days > 0:
        kwargs['created_after'] = (datetime.now() - timedelta(days=args.days)).isoformat()

    mrs = group.mergerequests.list(**kwargs)

    now = datetime.now(timezone.utc)
    data = []

    for mr in mrs:
        created_at = parse_dt(mr.created_at)
        age_hours = (now - created_at).total_seconds() / 3600
        comments = getattr(mr, 'user_notes_count', 0) or 0
        project_slug = extract_project_slug(mr.web_url)
        author = mr.author['username'] if mr.author else 'unknown'

        print(f'  !{mr.iid}  {age_hours:.1f}h  comments:{comments}  {author}  {project_slug}')
        data.append({
            'iid': mr.iid,
            'title': mr.title,
            'author': author,
            'project': project_slug,
            'age_hours': age_hours,
            'age_days': age_hours / 24.0,
            'comments': comments,
            'web_url': mr.web_url,
        })

    print(f'\nTotal open MRs found: {len(data)}')

    if not data:
        print('Nothing to display.')
        return

    df = pd.DataFrame(data).sort_values('age_hours', ascending=False).reset_index(drop=True)

    # Fetch merged + closed MRs for author stats (actual review time)
    hist_days = args.days if args.days > 0 else 90
    hist_since = (datetime.now() - timedelta(days=hist_days)).isoformat()
    print(f'\nFetching merged/closed MRs from last {hist_days} days for author stats...')

    hist_data = []
    for state in ('merged', 'closed'):
        hist_mrs = group.mergerequests.list(
            state=state,
            created_after=hist_since,
            per_page=100,
            iterator=True,
            include_subgroups=args.include_subgroups,
        )
        for mr in hist_mrs:
            created_at = parse_dt(mr.created_at)
            end_str = getattr(mr, 'merged_at', None) or getattr(mr, 'closed_at', None)
            end_dt = parse_dt(end_str) if end_str else now
            age_days = (end_dt - created_at).total_seconds() / 86400
            author = mr.author['username'] if mr.author else 'unknown'
            hist_data.append({
                'iid': mr.iid,
                'title': mr.title,
                'author': author,
                'project': extract_project_slug(mr.web_url),
                'age_days': age_days,
                'comments': getattr(mr, 'user_notes_count', 0) or 0,
                'state': state,
            })

    print(f'Merged/closed MRs fetched: {len(hist_data)}')

    hist_df = pd.DataFrame(hist_data) if hist_data else pd.DataFrame(
        columns=['iid', 'title', 'author', 'project', 'age_days', 'comments', 'state']
    )

    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')

    _save_review_dashboard(df, hist_df, group.full_name, args, output_dir, timestamp)


def _mr_label(row) -> str:
    title = row['title']
    title_short = (title[:40] + '...') if len(title) > 40 else title
    proj_parts = row['project'].split('/')
    proj_short = '/'.join(proj_parts[-2:]) if len(proj_parts) >= 2 else row['project']
    return f"!{row['iid']}  @{row['author']}  {title_short}  [{proj_short}]"


def _barh(ax, plot_df, x_col, colors, xlabel, title, ref_lines=None):
    y = np.arange(len(plot_df))
    ax.barh(y, plot_df[x_col], color=colors, height=0.7, edgecolor='white', linewidth=0.3)
    if ref_lines:
        x_max = plot_df[x_col].max()
        for val, color, label in ref_lines:
            if x_max >= val * 0.6:
                ax.axvline(x=val, color=color, linestyle='--', alpha=0.5, linewidth=1.1, label=label)
        ax.legend(fontsize=8, loc='lower right')
    labels = [_mr_label(row) for _, row in plot_df.iterrows()]
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7.5, family='monospace')
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_title(title, fontsize=11, pad=8)
    ax.set_facecolor('#f2f2f2')
    ax.grid(axis='x', color='white', linewidth=0.8)


def _save_review_dashboard(df, hist_df, group_name, args, output_dir, timestamp):
    top_n = args.top_n

    # Hot MRs: most commented, bar length = comment count
    hot = df.nlargest(top_n, 'comments').iloc[::-1].reset_index(drop=True)
    hot_norm = hot['comments'] / hot['comments'].max() if hot['comments'].max() > 0 else pd.Series(0.4, index=hot.index)
    hot_colors = [cm.YlOrRd(0.35 + 0.6 * v) for v in hot_norm]

    # Cold MRs: longest hanging with few comments (below median), bar length = age in days
    median_comments = df['comments'].median()
    cold_pool = df[df['comments'] <= max(median_comments, 1)]
    cold = cold_pool.nlargest(top_n, 'age_days').iloc[::-1].reset_index(drop=True)
    cold_norm = cold['age_days'] / cold['age_days'].max() if cold['age_days'].max() > 0 else pd.Series(0.4, index=cold.index)
    cold_colors = [cm.Blues(0.3 + 0.6 * v) for v in cold_norm]

    # Author stats: open MRs (age = time waiting) + merged/closed (age = actual review time)
    open_ages = df[['author', 'age_days', 'comments', 'iid']].copy()
    open_ages['state'] = 'opened'
    if not hist_df.empty:
        combined = pd.concat([open_ages, hist_df[['author', 'age_days', 'comments', 'iid', 'state']]], ignore_index=True)
    else:
        combined = open_ages

    hist_days = args.days if args.days > 0 else 90
    author_stats = (
        combined.groupby('author')
        .agg(avg_age_days=('age_days', 'mean'), mr_count=('iid', 'count'), total_comments=('comments', 'sum'))
        .reset_index()
        .sort_values('avg_age_days', ascending=False)
        .head(args.top_authors)
        .reset_index(drop=True)
    )
    author_plot = author_stats.iloc[::-1].reset_index(drop=True)

    fig_height = max(14, top_n * 1.05 + 5)
    fig = plt.figure(figsize=(24, fig_height), constrained_layout=True)
    fig.patch.set_facecolor('#f8f8f8')
    period_str = 'all time' if args.days == 0 else f'last {args.days} days'
    fig.suptitle(
        f'GitLab Arena!   {group_name}  |  {datetime.now().strftime("%d.%m.%Y")}  |  {period_str}  |  {len(df)} open MRs',
        fontsize=15,
        fontweight='bold',
    )

    gs = fig.add_gridspec(2, 2, width_ratios=[2.5, 1])
    ax_hot = fig.add_subplot(gs[0, 0])
    ax_cold = fig.add_subplot(gs[1, 0])
    ax_authors = fig.add_subplot(gs[:, 1])

    _barh(
        ax_hot, hot,
        x_col='comments',
        colors=hot_colors,
        xlabel='Number of comments',
        title=f'Top {len(hot)} hot MRs — most actively commented (bar length = comment count)',
    )
    # Annotate age on hot bars
    for i, row in hot.iterrows():
        ax_hot.text(
            row['comments'] + hot['comments'].max() * 0.005,
            i, f"{row['age_days']:.0f}d",
            va='center', fontsize=7.5, color='#555555',
        )

    _barh(
        ax_cold, cold,
        x_col='age_days',
        colors=cold_colors,
        xlabel='Age (days)',
        title=f'Top {len(cold)} cold MRs — hanging without activity (bar length = days open)',
        ref_lines=[(7, '#aaaaaa', '7d'), (14, '#888888', '14d'), (30, '#555555', '30d')],
    )
    # Annotate comment count on cold bars
    for i, row in cold.iterrows():
        ax_cold.text(
            row['age_days'] + cold['age_days'].max() * 0.005,
            i, f"{int(row['comments'])} comments",
            va='center', fontsize=7.5, color='#555555',
        )

    # Authors chart
    y2 = np.arange(len(author_plot))
    author_colors_arr = cm.OrRd(np.linspace(0.25, 0.85, len(author_plot)))
    ax_authors.barh(y2, author_plot['avg_age_days'], color=author_colors_arr, height=0.65, edgecolor='white', linewidth=0.3)
    x_max = author_plot['avg_age_days'].max()
    for i, row in author_plot.iterrows():
        ax_authors.text(
            row['avg_age_days'] + x_max * 0.01, i,
            f"{int(row['mr_count'])} MR{'s' if row['mr_count'] > 1 else ''}  /  {int(row['total_comments'])} comments",
            va='center', fontsize=8.5, color='#333333',
        )
    ax_authors.set_yticks(y2)
    ax_authors.set_yticklabels(author_plot['author'], fontsize=10)
    ax_authors.set_xlabel('Avg review age (days)', fontsize=10)
    ax_authors.set_title(
        f'Top {len(author_plot)} authors by avg review age\n(open + merged/closed, last {hist_days}d)',
        fontsize=11, pad=8,
    )
    ax_authors.set_facecolor('#f2f2f2')
    ax_authors.grid(axis='x', color='white', linewidth=0.8)

    path = output_dir / f'{timestamp}_mr_review_heat.png'
    plt.savefig(path, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close()
    print(f'\nSaved: {path.resolve()}')


if __name__ == '__main__':
    main()
