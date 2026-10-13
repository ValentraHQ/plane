# Wiki documentation spaces

> **Fork-specific (ValentraHQ).** Upstream Plane Community Edition has no workspace wiki; this builds on the
> fork's workspace wiki (`feat/workspace-wiki`) and nested pages (`feat/nested-pages`). Spaces apply to
> workspace wiki pages only. Project pages are unchanged.

Every workspace wiki page belongs to a **space**. A space groups related documentation (a team, product or
topic) and has its own page tree, access level and members.

## Data model

| Table                | Purpose                                                                                                                                        |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `wiki_spaces`        | name, `identifier` (2–12 chars `A-Z0-9`, unique per workspace), description, `logo_props`, `access`, `is_default`, `sort_order`, `archived_at` |
| `wiki_space_members` | explicit membership: `space`, `member`, `role` (20 admin, 15 editor, 5 viewer)                                                                 |
| `pages.space_id`     | nullable FK (`PROTECT`); set for every wiki page (`is_global`), null for project pages                                                         |

`pages.sort_order` (already in upstream) now orders siblings in the space tree.

### Migration to the default space

`0123_wiki_spaces` adds the tables and `pages.space_id`. `0124_wiki_pages_default_space` creates one default
**General** space per workspace that has wiki pages and assigns every wiki page to it, including archived
and soft-deleted pages. It only sets `space_id` (a bulk update), so page content, hierarchy, access, owner,
`updated_at`, version history and links are untouched. It is idempotent and safe to re-run. The logic is in
`plane/db/wiki_space_migration.py` so that it can be unit tested.

The default space is **open** and cannot be deleted.

## Access rules

Space roles are resolved in `plane/utils/wiki_permissions.py`. Page-level decisions go through
`plane/utils/page_access.py` (see [Page restrictions](page-restrictions.md)), which every wiki endpoint and, through
the `permissions` endpoint, the real-time server use.

Space role for a user:

| Who                                      | Role in an open space | Role in a restricted space |
| ---------------------------------------- | --------------------- | -------------------------- |
| Workspace guest, or not in the workspace | none                  | none                       |
| Workspace admin                          | admin                 | admin                      |
| Explicit space member                    | their member role     | their member role          |
| Other workspace member                   | editor                | none                       |

Page permissions inside a space:

- **view**: has a space role, and the page is public or owned by the user
- **edit** (title, content, create sub-pages): view and role ≥ editor
- **manage** (lock, archive, delete, access, move): view and (space admin, or owner who is still an editor)

Users without a role never see that a space or its pages exist: they get 404, not 403. Guests and people
outside the workspace get 403 from the workspace permission check.

These rules are then narrowed by inherited page restrictions and private parent pages: see [Page restrictions](page-restrictions.md).

## API

All routes are under `/api/workspaces/<slug>/wiki/`.

| Method & path                                   | Who                                     | Notes                                                                                   |
| ----------------------------------------------- | --------------------------------------- | --------------------------------------------------------------------------------------- |
| `GET spaces/`                                   | workspace admin/member                  | spaces the user can see, with `my_role` and `page_count`                                |
| `POST spaces/`                                  | workspace admin/member                  | the creator becomes space admin                                                         |
| `GET/PATCH/DELETE spaces/<id>/`                 | view / space admin                      | delete is refused for the default space and for non-empty spaces                        |
| `GET/POST spaces/<id>/members/`                 | view / space admin                      | guests cannot be added                                                                  |
| `PATCH/DELETE spaces/<id>/members/<member_id>/` | space admin                             |                                                                                         |
| `GET spaces/<id>/pages-tree/`                   | view                                    | lightweight list of visible, non-archived pages for the sidebar                         |
| `GET pages/?space_id=&parent_id=`               | view                                    | page list filtered by space and/or parent                                               |
| `POST pages/`                                   | editor                                  | needs `space` or `parent`; sub-pages always use the parent's space                      |
| `GET pages/<id>/permissions/`                   | view                                    | `can_view`, `can_edit`, `can_manage`, `can_edit_content`                                |
| `POST pages/<id>/move/`                         | manage (and editor in the target space) | `{space?, parent?, sort_order?}`; the sub-tree moves with the page; cycles are rejected |

Project pages also have `GET projects/<project_id>/pages/<id>/permissions/` for real-time authorization.

## Real-time collaboration

Before this change the live server only checked that the cookie belonged to a signed-in user. Any
authenticated user could open, and write to, any page document whose id they knew.

`apps/live/src/lib/auth.ts` now calls the page's `permissions` endpoint with the connecting user's cookie
when a connection is authenticated:

- no `can_view`: the connection is refused (`AUTH_FORBIDDEN`) before any document data is sent
- `can_view` without `can_edit_content` (viewers, locked or archived pages): the connection is read-only, so
  the server neither applies nor broadcasts that client's updates

This covers project pages as well as wiki pages. Permissions are checked when a connection opens; changes
to a user's role take effect when they reconnect.

## Web

- `/<slug>/wiki`: directory of spaces, with **Create space** (hidden for guests)
- `/<slug>/wiki/spaces/<id>`: space home with the page list, **New page**, Members, Space settings, Delete
- page view: a persistent sidebar with a space switcher and the page tree. Sub-pages can be added from the
  tree. Pages can be dragged to reorder or nest them, dropped below the tree to move them to the top level,
  or moved with **Move to…** (any space and parent the user can write to).
- breadcrumbs show the space.

## Tests

- `plane/tests/unit/test_wiki_space_migration.py`: default-space migration (hierarchy, archived and deleted
  pages, versions and project pages untouched, one space per workspace, identifier clash, idempotency)
- `plane/tests/contract/app/test_wiki_spaces_app.py`: space CRUD, members, permission matrix, move, tree,
  project page permissions
- `plane/tests/contract/app/test_workspace_wiki_app.py`: wiki pages within spaces
