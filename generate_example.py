"""Generate a sample dashboard PNG with fake data for the README."""
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from collections import defaultdict
from datetime import datetime

sns.set_style('whitegrid')
plt.rcParams['font.size'] = 11

users = [
    'alice', 'bob', 'carol', 'dave', 'eve',
    'frank', 'grace', 'henry', 'iris', 'jack',
]

authored   = [12, 9, 8, 7, 6, 5, 4, 4, 3, 2]
approved   = [4,  7, 3, 9, 2, 6, 5, 1, 3, 8]
commented  = [3,  5, 6, 4, 8, 2, 3, 7, 4, 2]

stats_df = pd.DataFrame({
    'user': users,
    'authored': authored,
    'approved': approved,
    'commented': commented,
})
stats_df['review_activity'] = stats_df['approved'] + stats_df['commented']
stats_df['total'] = stats_df['authored'] + stats_df['review_activity']
stats_df = stats_df.sort_values('total', ascending=False).reset_index(drop=True)

approved_count = defaultdict(int, dict(zip(users, approved)))
commented_count = defaultdict(int, dict(zip(users, commented)))

top_n = 10
group_name = 'acme-corp'

fig, axes = plt.subplots(2, 2, figsize=(20, 16))
fig.suptitle(
    f'GitLab MR Activity — {group_name}\n'
    f'Last 30 days ({datetime.now().strftime("%d.%m.%Y")}) — Top {top_n}',
    fontsize=18,
    fontweight='bold',
)

top_authors = stats_df.nlargest(top_n, 'authored')
sns.barplot(data=top_authors, x='authored', y='user', hue='user', palette='Blues_d', ax=axes[0, 0], legend=False)
axes[0, 0].set_title(f'Top {top_n} MR authors')
axes[0, 0].set_xlabel('MRs created')
axes[0, 0].set_ylabel('')

top_reviewers = stats_df.nlargest(top_n, 'review_activity')
sns.barplot(data=top_reviewers, x='review_activity', y='user', hue='user', palette='Greens_d', ax=axes[0, 1], legend=False)
axes[0, 1].set_title(f'Top {top_n} reviewers (approvals + comments)')
axes[0, 1].set_xlabel('Review activity')
axes[0, 1].set_ylabel('')

ax = axes[1, 0]
total_mr = stats_df['authored'].sum()
total_approved = sum(approved_count.values())
total_commented = sum(commented_count.values())
total_all = total_mr + total_approved + total_commented

sizes = [total_mr, total_approved, total_commented]
labels = ['MRs created', 'Approvals', 'Comments']
colors = ['#1f77b4', '#2ca02c', '#ff7f0e']
ax.pie(
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

top_users = stats_df.head(top_n)
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
axes[1, 1].set_title(f'Activity breakdown (top {top_n})')
axes[1, 1].legend()

plt.tight_layout(rect=[0, 0, 1, 0.95])

out = Path('docs')
out.mkdir(exist_ok=True)
path = out / 'dashboard_example.png'
plt.savefig(path, dpi=150, bbox_inches='tight')
plt.close()
print(f'Saved: {path.resolve()}')

