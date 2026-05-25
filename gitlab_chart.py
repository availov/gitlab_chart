import gitlab
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import argparse
from collections import defaultdict, Counter

sns.set_style('whitegrid')
plt.rcParams['font.size'] = 11


def main():
    parser = argparse.ArgumentParser(description='GitLab group MR activity dashboard')
    parser.add_argument('--url', default='https://gitlab.com', help='GitLab URL')
    parser.add_argument('--token', required=True, help='Personal access token')
    parser.add_argument('--group', required=True, help='Group path or ID')
    parser.add_argument('--days', type=int, default=7, help='Number of days to look back')
    parser.add_argument('--top-n', type=int, default=10, help='Number of users in top charts (default: 10)')
    parser.add_argument('--output', default='gitlab_charts', help='Output directory')
    parser.add_argument('--include-subgroups', action='store_true', default=True)
    parser.add_argument('--user', default=None, help='Username for detailed per-user report')

    args = parser.parse_args()

    gl = gitlab.Gitlab(args.url, private_token=args.token, ssl_verify=True)
    group = gl.groups.get(args.group)
    print(f'Group: {group.full_name}')
    print(f'Period: last {args.days} days')
    print(f'Top N: {args.top_n}\n')

    mrs = group.mergerequests.list(
        state='all',
        created_after=(datetime.now() - timedelta(days=args.days)).isoformat(),
        per_page=100,
        iterator=True,
        include_subgroups=args.include_subgroups,
    )

    data = []
    mr_count = 0
    project_cache = {}

    for group_mr in mrs:
        mr_count += 1
        print(f'  Processing MR #{mr_count} (iid {group_mr.iid})...')

        try:
            if group_mr.project_id not in project_cache:
                project_cache[group_mr.project_id] = gl.projects.get(group_mr.project_id)
            project = project_cache[group_mr.project_id]
            full_mr = project.mergerequests.get(group_mr.iid)
        except Exception as e:
            print(f'    [!] Failed to fetch MR #{group_mr.iid}: {e}')
            continue

        author = full_mr.author['username'] if full_mr.author else 'unknown'

        try:
            approvals = full_mr.approvals.get()
            approvers = [a['user']['username'] for a in approvals.approved_by] if approvals else []
        except Exception:
            approvers = []

        commentators = set()
        try:
            notes = full_mr.notes.list(all=True, per_page=100)
            for note in notes:
                if getattr(note, 'system', False):
                    continue
                note_author = note.author['username'] if note.author else None
                if note_author and note_author != author:
                    commentators.add(note_author)
        except Exception:
            pass

        data.append({
            'mr_iid': full_mr.iid,
            'mr_title': full_mr.title,
            'project': project.path_with_namespace,
            'author': author,
            'approvers': approvers,
            'commentators': list(commentators),
        })

    print(f'\nTotal MRs processed: {mr_count}')

    if not data:
        print('No MRs found for the given period.')
        return

    df = pd.DataFrame(data)

    authored = Counter(df['author'])
    approved_count = defaultdict(int)
    commented_count = defaultdict(int)

    for _, row in df.iterrows():
        for user in row['approvers']:
            approved_count[user] += 1
        for user in row['commentators']:
            commented_count[user] += 1

    total_approvals = sum(approved_count.values())
    total_comments = sum(commented_count.values())
    print(f'Approvals: {total_approvals}')
    print(f'Comments on others\' MRs: {total_comments}')
    print(f'Total review activity: {total_approvals + total_comments}')

    users = set(authored.keys()) | set(approved_count.keys()) | set(commented_count.keys())
    stats = []
    for user in users:
        approved = approved_count.get(user, 0)
        commented = commented_count.get(user, 0)
        stats.append({
            'user': user,
            'authored': authored.get(user, 0),
            'approved': approved,
            'commented': commented,
            'review_activity': approved + commented,
            'total': authored.get(user, 0) + approved + commented,
        })

    stats_df = pd.DataFrame(stats).sort_values('total', ascending=False)

    if args.user:
        u = args.user
        print(f'\n{"=" * 60}')
        print(f'  {u}')
        print(f'{"=" * 60}')

        authored_mrs = df[df['author'] == u][['mr_iid', 'mr_title', 'project']]
        print(f'\nAuthored MRs ({len(authored_mrs)}):')
        if not authored_mrs.empty:
            for _, r in authored_mrs.iterrows():
                print(f'  #{r["mr_iid"]:>4}  [{r["project"]}]  {r["mr_title"]}')
        else:
            print('  none')

        approved_mrs = df[df['approvers'].apply(lambda x: u in x)][['mr_iid', 'mr_title', 'project', 'author']]
        print(f'\nApprovals on others\' MRs ({len(approved_mrs)}):')
        if not approved_mrs.empty:
            for _, r in approved_mrs.iterrows():
                print(f'  #{r["mr_iid"]:>4}  [{r["project"]}]  {r["mr_title"]}  (author: {r["author"]})')
        else:
            print('  none')

        commented_mrs = df[df['commentators'].apply(lambda x: u in x)][['mr_iid', 'mr_title', 'project', 'author']]
        print(f'\nComments on others\' MRs ({len(commented_mrs)}):')
        if not commented_mrs.empty:
            for _, r in commented_mrs.iterrows():
                print(f'  #{r["mr_iid"]:>4}  [{r["project"]}]  {r["mr_title"]}  (author: {r["author"]})')
        else:
            print('  none')

        user_row = stats_df[stats_df['user'] == u]
        if not user_row.empty:
            rank = stats_df.reset_index(drop=True).index[stats_df['user'] == u].tolist()
            rank_pos = rank[0] + 1 if rank else '?'
            row = user_row.iloc[0]
            print(f'\nRank: #{rank_pos} of {len(stats_df)}')
            print(f'  authored={row["authored"]}  approved={row["approved"]}  commented={row["commented"]}')
            print(f'  review_activity={row["review_activity"]}  total={row["total"]}')
        else:
            print(f'\nUser "{u}" not found in stats for this period.')

        print(f'{"=" * 60}\n')

    print('\nTOP CONTRIBUTORS')
    print(stats_df.head(args.top_n).to_string(index=False))

    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')

    _save_dashboard(stats_df, approved_count, commented_count, group.full_name, args, output_dir, timestamp)


def _save_dashboard(stats_df, approved_count, commented_count, group_name, args, output_dir, timestamp):
    fig, axes = plt.subplots(2, 2, figsize=(20, 16))
    fig.suptitle(
        f'GitLab MR Activity — {group_name}\n'
        f'Last {args.days} days ({datetime.now().strftime("%d.%m.%Y")}) — Top {args.top_n}',
        fontsize=18,
        fontweight='bold',
    )

    top_authors = stats_df.nlargest(args.top_n, 'authored')
    sns.barplot(data=top_authors, x='authored', y='user', hue='user', palette='Blues_d', ax=axes[0, 0], legend=False)
    axes[0, 0].set_title(f'Top {args.top_n} MR authors')
    axes[0, 0].set_xlabel('MRs created')
    axes[0, 0].set_ylabel('')

    top_reviewers = stats_df.nlargest(args.top_n, 'review_activity')
    sns.barplot(data=top_reviewers, x='review_activity', y='user', hue='user', palette='Greens_d', ax=axes[0, 1], legend=False)
    axes[0, 1].set_title(f'Top {args.top_n} reviewers (approvals + comments)')
    axes[0, 1].set_xlabel('Review activity')
    axes[0, 1].set_ylabel('')

    ax = axes[1, 0]
    total_mr = stats_df['authored'].sum()
    total_approved = sum(approved_count.values())
    total_commented = sum(commented_count.values())
    total_all = total_mr + total_approved + total_commented

    if total_all > 0:
        sizes = [total_mr, total_approved, total_commented]
        labels = ['MRs created', 'Approvals', 'Comments']
        colors = ['#1f77b4', '#2ca02c', '#ff7f0e']
        wedges, texts, autotexts = ax.pie(
            sizes,
            explode=(0.03, 0.03, 0.03),
            labels=labels,
            colors=colors,
            autopct='%1.1f%%',
            startangle=90,
            pctdistance=0.75,
            textprops={'fontsize': 12},
        )
        centre_circle = plt.Circle((0, 0), 0.65, fc='white')
        ax.add_artist(centre_circle)
        ax.text(0, 0.2, f'{total_all}', fontsize=28, fontweight='bold', ha='center')
        ax.text(0, -0.15, 'Total activities', fontsize=11, ha='center')
        ax.set_title('Team activity breakdown\n(MRs / Approvals / Comments)', fontsize=16, pad=20)

    top_users = stats_df.head(args.top_n)
    x = range(len(top_users))
    width = 0.6

    axes[1, 1].bar(x, top_users['authored'], width, label='MRs created', color='#1f77b4')
    axes[1, 1].bar(x, top_users['approved'], width, bottom=top_users['authored'], label='Approvals', color='#2ca02c')
    axes[1, 1].bar(
        x,
        top_users['commented'],
        width,
        bottom=top_users['authored'] + top_users['approved'],
        label='Comments',
        color='#ff7f0e',
    )
    axes[1, 1].set_xticks(x)
    axes[1, 1].set_xticklabels(top_users['user'], rotation=45, ha='right')
    axes[1, 1].set_title(f'Activity breakdown (top {args.top_n})')
    axes[1, 1].legend()

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    path = output_dir / f'{timestamp}_dashboard.png'
    plt.savefig(path, dpi=250, bbox_inches='tight')
    plt.close()
    print(f'\nDashboard saved: {path.resolve()}')


if __name__ == '__main__':
    main()