# Page restrictions

> **Fork-specific (ValentraHQ).** Upstream Plane Community Edition has page access (public / private) but no
> per-person restrictions and no inheritance. This applies to workspace wiki pages and project pages.

A page can be limited to named people for **viewing**, **editing**, or both. Restrictions apply to the page and
everything below it, Confluence style: a sub-page is never more open than its most restrictive ancestor.
Restrictions only narrow access. They never give anyone more than their space or project role allows.

## Rules

All page decisions are made by one resolver, `plane/utils/page_access.py`. It has two layers.

**1. Base rules from the user's role** (unchanged from before):

| Page type    | Can view                                                                 | Can edit                         | Can manage (lock, archive, delete, move, restrictions) |
| ------------ | ------------------------------------------------------------------------ | -------------------------------- | ------------------------------------------------------ |
| Wiki page    | any space role; private pages: owner only                                | space editor or admin            | space admin, or the owner while still an editor        |
| Project page | project member; guests only their own pages unless the project allows it | owner, or member on public pages | owner or project admin                                 |

**2. Inherited restrictions and privacy**, checked on the page and every ancestor:

- **Private ancestor:** hides the whole sub-tree from everyone except that ancestor's owner, admins included.
  Before this change, a public child of a private page was visible to everyone.
- **View restriction** on the page or any ancestor: the user must be listed, be the owner of the restricted
  page, or be an admin. Otherwise the page and its sub-pages are hidden.
- **Edit restriction** on the page or any ancestor: same test, for editing and managing. Users who fail it keep
  read access.

"Admins" means space admins (including workspace admins) for wiki pages and project admins for project pages.

A page that the user cannot view is reported as **404**, so its existence is not revealed. Adding a sub-page
under a page, or moving a page under it, requires edit rights on that page.

## Where it is enforced

- Wiki and project page list, detail, tree, sub-page counts and pages summary
- Description (content) read and write
- Version history
- The `permissions` endpoints that the real-time server checks before opening a connection: hidden pages are
  refused, and edit-restricted pages give a read-only connection
- Global search and @-mention page search
- Favourites and recent visits, which would otherwise show a title the user can no longer see
- Duplicating a page: the copy keeps the original's own restrictions, so copying never widens access

Lists and search use one recursive SQL query (`exclude_hidden`). Single pages use an ancestor walk
(`page_permissions`). A test checks that both give the same answer for every user and page.

## API

Restrictions on wiki pages:

```
GET /api/workspaces/<slug>/wiki/pages/<page_id>/restrictions/
PUT /api/workspaces/<slug>/wiki/pages/<page_id>/restrictions/
```

Restrictions on project pages:

```
GET /api/workspaces/<slug>/projects/<project_id>/pages/<page_id>/restrictions/
PUT /api/workspaces/<slug>/projects/<project_id>/pages/<page_id>/restrictions/
```

`GET` returns the page's own lists, the restricted ancestors it inherits from, and whether the user may change
them:

```json
{
  "view": ["<user id>"],
  "edit": [],
  "inherited": [{ "page": "<id>", "name": "Handbook", "view": true, "edit": false }],
  "can_manage": true
}
```

`PUT` takes `{"view": [...], "edit": [...]}`; either key may be omitted. It requires manage rights. Every listed
person must already have access to the page's space or project. Removed entries are soft-deleted, keeping who
removed them and when.

Page detail responses (wiki and project) now include `permissions`: `{can_view, can_edit, can_manage,
can_edit_content}`. The space tree marks pages with their own restrictions (`view_restricted`,
`edit_restricted`).

## Web

- **Restrictions** in the page menu (editor toolbar and list rows) opens a dialog. It has two member pickers,
  _Who can view_ and _Who can edit_, and shows any restrictions inherited from parent pages.
- A shield icon marks restricted pages in the space tree.
- Page permissions in the web app use the API's verdict once the page detail is loaded, so inherited
  restrictions also make the editor read-only.

## Data model

`page_restrictions`: `workspace`, `page`, `kind` (`view` / `edit`), `member`. It is unique per page, kind and
member among rows that are not deleted. Migration: `0125_page_restrictions`.

## Limitations

- Permissions are checked when a real-time connection opens. A change takes effect when the editor reconnects.
- Restrictions are per person; Community Edition has no groups or teams to restrict to.
- An admin can see and lift restrictions, but cannot see below another person's private page.
