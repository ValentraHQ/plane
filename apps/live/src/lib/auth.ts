/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { IncomingHttpHeaders } from "http";
import type { TUserDetails } from "@plane/editor";
import { logger } from "@plane/logger";
import { AppError } from "@/lib/errors";
// services
import { getPageService } from "@/services/page/handler";
import { UserService } from "@/services/user.service";
// types
import type { HocusPocusServerContext, TDocumentTypes } from "@/types";

/**
 * Authenticate the user
 * @param requestHeaders - The request headers
 * @param context - The context
 * @param token - The token
 * @returns The authenticated user
 */
export const onAuthenticate = async ({
  requestHeaders,
  requestParameters,
  context,
  token,
  documentName,
  connection,
}: {
  requestHeaders: IncomingHttpHeaders;
  context: HocusPocusServerContext;
  requestParameters: URLSearchParams;
  token: string;
  documentName: string;
  connection: { readOnly: boolean };
}) => {
  let cookie: string | undefined = undefined;
  let userId: string | undefined = undefined;

  // Extract cookie (fallback to request headers) and userId from token (for scenarios where
  // the cookies are not passed in the request headers)
  try {
    const parsedToken = JSON.parse(token) as TUserDetails;
    userId = parsedToken.id;
    cookie = parsedToken.cookie;
  } catch (error) {
    const appError = new AppError(error, {
      context: { operation: "onAuthenticate" },
    });
    logger.error("Token parsing failed, using request headers", appError);
  } finally {
    // If cookie is still not found, fallback to request headers
    if (!cookie) {
      cookie = requestHeaders.cookie?.toString();
    }
  }

  if (!cookie || !userId) {
    const appError = new AppError("Credentials not provided", { code: "AUTH_MISSING_CREDENTIALS" });
    logger.error("Credentials not provided", appError);
    throw appError;
  }

  // set cookie in context, so it can be used throughout the ws connection
  context.cookie = cookie ?? requestParameters.get("cookie") ?? "";
  context.documentType = requestParameters.get("documentType")?.toString() as TDocumentTypes;
  context.projectId = requestParameters.get("projectId");
  context.userId = userId;
  context.workspaceSlug = requestParameters.get("workspaceSlug");

  const authResult = await handleAuthentication({
    cookie: context.cookie,
    userId: context.userId,
  });

  // authentication says who the user is; this decides what they may do with this page
  await authorizeDocument({ context, documentName, connection });

  return authResult;
};

/**
 * Authorize a connection to one page (documentName is the page id).
 * - no view permission: the connection is refused before any document data is sent
 * - view without edit (viewers, locked or archived pages): the connection is read-only,
 *   so the server neither applies nor broadcasts that client's updates
 * The API decides, using the connecting user's own cookie.
 */
export const authorizeDocument = async ({
  context,
  documentName,
  connection,
}: {
  context: HocusPocusServerContext;
  documentName: string;
  connection: { readOnly: boolean };
}) => {
  let canView = false;
  let canEditContent = false;
  try {
    const permissions = await getPageService(context.documentType, context).fetchPermissions(documentName);
    canView = !!permissions?.can_view;
    canEditContent = !!permissions?.can_edit_content;
  } catch (error) {
    logger.error("Page authorization failed", new AppError(error, { context: { operation: "authorizeDocument" } }));
  }
  if (!canView) {
    throw new AppError("Not authorized to open this page", { code: "AUTH_FORBIDDEN" });
  }
  connection.readOnly = !canEditContent;
};

export const handleAuthentication = async ({ cookie, userId }: { cookie: string; userId: string }) => {
  // fetch current user info
  try {
    const userService = new UserService();
    const user = await userService.currentUser(cookie);
    if (user.id !== userId) {
      throw new AppError("Authentication unsuccessful: User ID mismatch", { code: "AUTH_USER_MISMATCH" });
    }

    return {
      user: {
        id: user.id,
        name: user.display_name,
      },
    };
  } catch (error) {
    const appError = new AppError(error, {
      context: { operation: "handleAuthentication" },
    });
    logger.error("Authentication failed", appError);
    throw new AppError("Authentication unsuccessful", { code: appError.code });
  }
};
