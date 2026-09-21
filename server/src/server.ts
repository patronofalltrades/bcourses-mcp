import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import * as z from "zod/v4";
import { CanvasClient } from "./canvas-client.js";

const id = z.union([z.string().min(1), z.number().int().nonnegative()]).transform(String);
const pageSize = z.number().int().min(1).max(100).default(50);
const readAnnotations = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true } as const;
const createAnnotations = { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: true } as const;
const updateAnnotations = { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true } as const;

function result(value: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }] };
}

function coursePath(courseId: string, suffix = "") {
  return `/api/v1/courses/${encodeURIComponent(courseId)}${suffix}`;
}

export function createServer(client: CanvasClient): McpServer {
  const server = new McpServer(
    { name: "bcourses-student", version: "0.1.0" },
    {
      instructions:
        "Student-scoped bCourses access. Never claim a submission, post, message, or update succeeded unless its tool returned success. Before consequential writes, summarize the target and content for user confirmation. Never create or modify instructor-owned course content, grades, rosters, assignments, modules, pages, announcements, or course events.",
    },
  );

  server.registerTool("get_my_profile", {
    description: "Get the authenticated bCourses user's profile.", inputSchema: {}, annotations: readAnnotations,
  }, async () => result(await client.request("GET", "/api/v1/users/self/profile")));

  server.registerTool("list_courses", {
    description: "List courses visible to the authenticated user.",
    inputSchema: {
      enrollmentState: z.enum(["active", "invited_or_pending", "completed"]).optional(),
      state: z.array(z.enum(["unpublished", "available", "completed", "deleted"])).optional(),
      perPage: pageSize,
    }, annotations: readAnnotations,
  }, async ({ enrollmentState, state, perPage }) => result(await client.request("GET", "/api/v1/courses", {
    query: { enrollment_state: enrollmentState, "state[]": state, per_page: perPage, "include[]": ["term", "total_scores", "permissions"] },
  })));

  server.registerTool("get_course", {
    description: "Get course metadata, syllabus, term, and the current user's permissions.",
    inputSchema: { courseId: id }, annotations: readAnnotations,
  }, async ({ courseId }) => result(await client.request("GET", coursePath(courseId), {
    query: { "include[]": ["syllabus_body", "term", "permissions", "course_image"] },
  })));

  server.registerTool("search_course_content", {
    description: "Search titles and text across assignments, pages, modules, and discussions in one course.",
    inputSchema: { courseId: id, query: z.string().min(2).max(200), limitPerType: z.number().int().min(1).max(25).default(10) },
    annotations: readAnnotations,
  }, async ({ courseId, query, limitPerType }) => {
    const [assignments, pages, modules, discussions] = await Promise.all([
      client.request<unknown[]>("GET", coursePath(courseId, "/assignments"), { query: { per_page: 100 } }),
      client.request<unknown[]>("GET", coursePath(courseId, "/pages"), { query: { per_page: 100 } }),
      client.request<unknown[]>("GET", coursePath(courseId, "/modules"), { query: { per_page: 100, "include[]": ["items"] } }),
      client.request<unknown[]>("GET", coursePath(courseId, "/discussion_topics"), { query: { per_page: 100 } }),
    ]);
    const needle = query.toLocaleLowerCase();
    const filter = (items: unknown[]) => items.filter(item => JSON.stringify(item).toLocaleLowerCase().includes(needle)).slice(0, limitPerType);
    return result({ assignments: filter(assignments), pages: filter(pages), modules: filter(modules), discussions: filter(discussions) });
  });

  server.registerTool("list_modules", {
    description: "List course modules, optionally with module items.",
    inputSchema: { courseId: id, includeItems: z.boolean().default(true), perPage: pageSize }, annotations: readAnnotations,
  }, async ({ courseId, includeItems, perPage }) => result(await client.request("GET", coursePath(courseId, "/modules"), {
    query: { per_page: perPage, "include[]": includeItems ? ["items", "content_details"] : undefined },
  })));

  server.registerTool("get_module", {
    description: "Get one course module.", inputSchema: { courseId: id, moduleId: id }, annotations: readAnnotations,
  }, async ({ courseId, moduleId }) => result(await client.request("GET", coursePath(courseId, `/modules/${encodeURIComponent(moduleId)}`), {
    query: { "include[]": ["items", "content_details"] },
  })));

  server.registerTool("list_module_items", {
    description: "List items in a course module.",
    inputSchema: { courseId: id, moduleId: id, perPage: pageSize }, annotations: readAnnotations,
  }, async ({ courseId, moduleId, perPage }) => result(await client.request("GET", coursePath(courseId, `/modules/${encodeURIComponent(moduleId)}/items`), {
    query: { per_page: perPage, "include[]": ["content_details"] },
  })));

  server.registerTool("list_pages", {
    description: "List pages in a course.", inputSchema: { courseId: id, searchTerm: z.string().max(200).optional(), perPage: pageSize }, annotations: readAnnotations,
  }, async ({ courseId, searchTerm, perPage }) => result(await client.request("GET", coursePath(courseId, "/pages"), {
    query: { search_term: searchTerm, per_page: perPage },
  })));

  server.registerTool("get_page", {
    description: "Get a course page by URL slug or ID.", inputSchema: { courseId: id, pageUrlOrId: id }, annotations: readAnnotations,
  }, async ({ courseId, pageUrlOrId }) => result(await client.request("GET", coursePath(courseId, `/pages/${encodeURIComponent(pageUrlOrId)}`))));

  server.registerTool("list_assignments", {
    description: "List assignments and due dates in a course.",
    inputSchema: { courseId: id, searchTerm: z.string().max(200).optional(), bucket: z.enum(["past", "overdue", "undated", "ungraded", "unsubmitted", "upcoming", "future"]).optional(), perPage: pageSize }, annotations: readAnnotations,
  }, async ({ courseId, searchTerm, bucket, perPage }) => result(await client.request("GET", coursePath(courseId, "/assignments"), {
    query: { search_term: searchTerm, bucket, per_page: perPage, "include[]": ["submission", "all_dates"] },
  })));

  server.registerTool("get_assignment", {
    description: "Get one assignment and the authenticated student's submission summary.",
    inputSchema: { courseId: id, assignmentId: id }, annotations: readAnnotations,
  }, async ({ courseId, assignmentId }) => result(await client.request("GET", coursePath(courseId, `/assignments/${encodeURIComponent(assignmentId)}`), {
    query: { "include[]": ["submission", "all_dates"] },
  })));

  server.registerTool("list_announcements", {
    description: "List announcements for a course.", inputSchema: { courseId: id, startDate: z.string().datetime().optional(), endDate: z.string().datetime().optional(), perPage: pageSize }, annotations: readAnnotations,
  }, async ({ courseId, startDate, endDate, perPage }) => result(await client.request("GET", "/api/v1/announcements", {
    query: { "context_codes[]": [`course_${courseId}`], start_date: startDate, end_date: endDate, per_page: perPage },
  })));

  server.registerTool("list_discussions", {
    description: "List discussion topics in a course.", inputSchema: { courseId: id, searchTerm: z.string().max(200).optional(), perPage: pageSize }, annotations: readAnnotations,
  }, async ({ courseId, searchTerm, perPage }) => result(await client.request("GET", coursePath(courseId, "/discussion_topics"), {
    query: { search_term: searchTerm, per_page: perPage },
  })));

  server.registerTool("get_discussion", {
    description: "Get a discussion topic with its entries and replies.", inputSchema: { courseId: id, topicId: id }, annotations: readAnnotations,
  }, async ({ courseId, topicId }) => result(await client.request("GET", coursePath(courseId, `/discussion_topics/${encodeURIComponent(topicId)}/view`))));

  server.registerTool("list_calendar_events", {
    description: "List calendar events visible to the authenticated user.",
    inputSchema: { courseId: id.optional(), startDate: z.string().datetime().optional(), endDate: z.string().datetime().optional(), perPage: pageSize }, annotations: readAnnotations,
  }, async ({ courseId, startDate, endDate, perPage }) => result(await client.request("GET", "/api/v1/calendar_events", {
    query: { "context_codes[]": courseId ? [`course_${courseId}`] : undefined, start_date: startDate, end_date: endDate, per_page: perPage },
  })));

  server.registerTool("list_files", {
    description: "List files accessible in a course.", inputSchema: { courseId: id, searchTerm: z.string().max(200).optional(), perPage: pageSize }, annotations: readAnnotations,
  }, async ({ courseId, searchTerm, perPage }) => result(await client.request("GET", coursePath(courseId, "/files"), {
    query: { search_term: searchTerm, per_page: perPage },
  })));

  server.registerTool("get_file", {
    description: "Get metadata and an authorized URL for one Canvas file.", inputSchema: { fileId: id }, annotations: readAnnotations,
  }, async ({ fileId }) => result(await client.request("GET", `/api/v1/files/${encodeURIComponent(fileId)}`)));

  server.registerTool("get_my_submission", {
    description: "Get the authenticated student's submission for an assignment.", inputSchema: { courseId: id, assignmentId: id }, annotations: readAnnotations,
  }, async ({ courseId, assignmentId }) => {
    const profile = await client.request<{ id: string | number }>("GET", "/api/v1/users/self/profile");
    return result(await client.request("GET", coursePath(courseId, `/assignments/${encodeURIComponent(assignmentId)}/submissions/${encodeURIComponent(String(profile.id))}`), {
      query: { "include[]": ["submission_comments", "rubric_assessment", "full_rubric_assessment", "visibility"] },
    }));
  });

  server.registerTool("list_conversations", {
    description: "List the authenticated user's Canvas Inbox conversations.",
    inputSchema: { scope: z.enum(["unread", "starred", "archived", "sent"]).optional(), filter: z.string().max(200).optional(), perPage: pageSize }, annotations: readAnnotations,
  }, async ({ scope, filter, perPage }) => result(await client.request("GET", "/api/v1/conversations", { query: { scope, filter, per_page: perPage } })));

  server.registerTool("get_conversation", {
    description: "Get a Canvas Inbox conversation and its messages.", inputSchema: { conversationId: id }, annotations: readAnnotations,
  }, async ({ conversationId }) => result(await client.request("GET", `/api/v1/conversations/${encodeURIComponent(conversationId)}`)));

  server.registerTool("upload_submission_file", {
    description: "Upload a file for the authenticated student's assignment submission. Returns a Canvas file object; call submit_assignment with its ID to submit it.",
    inputSchema: { courseId: id, assignmentId: id, fileName: z.string().min(1).max(255), contentType: z.string().min(1).max(150), contentBase64: z.string().min(1) }, annotations: createAnnotations,
  }, async input => {
    const profile = await client.request<{ id: string | number }>("GET", "/api/v1/users/self/profile");
    return result(await client.uploadSubmissionFile({ ...input, userId: String(profile.id) }));
  });

  server.registerTool("submit_assignment", {
    description: "Submit or resubmit the authenticated student's work. Requires an explicit submission type and matching content.",
    inputSchema: {
      courseId: id, assignmentId: id,
      submissionType: z.enum(["online_text_entry", "online_url", "online_upload"]),
      text: z.string().max(200_000).optional(), url: z.string().url().optional(), fileIds: z.array(id).max(20).optional(),
    }, annotations: createAnnotations,
  }, async ({ courseId, assignmentId, submissionType, text, url, fileIds }) => {
    if (submissionType === "online_text_entry" && !text) throw new Error("text is required for online_text_entry");
    if (submissionType === "online_url" && !url) throw new Error("url is required for online_url");
    if (submissionType === "online_upload" && (!fileIds || fileIds.length === 0)) throw new Error("fileIds are required for online_upload");
    return result(await client.request("POST", coursePath(courseId, `/assignments/${encodeURIComponent(assignmentId)}/submissions`), {
      body: { submission: { submission_type: submissionType, body: text, url, file_ids: fileIds } },
    }));
  });

  server.registerTool("post_discussion_entry", {
    description: "Post a top-level entry to a course discussion as the authenticated user.",
    inputSchema: { courseId: id, topicId: id, message: z.string().min(1).max(200_000) }, annotations: createAnnotations,
  }, async ({ courseId, topicId, message }) => result(await client.request("POST", coursePath(courseId, `/discussion_topics/${encodeURIComponent(topicId)}/entries`), { body: { message } })));

  server.registerTool("reply_to_discussion_entry", {
    description: "Reply to a specific course discussion entry as the authenticated user.",
    inputSchema: { courseId: id, topicId: id, entryId: id, message: z.string().min(1).max(200_000) }, annotations: createAnnotations,
  }, async ({ courseId, topicId, entryId, message }) => result(await client.request("POST", coursePath(courseId, `/discussion_topics/${encodeURIComponent(topicId)}/entries/${encodeURIComponent(entryId)}/replies`), { body: { message } })));

  server.registerTool("add_submission_comment", {
    description: "Add a text comment to the authenticated student's own submission.",
    inputSchema: { courseId: id, assignmentId: id, comment: z.string().min(1).max(20_000) }, annotations: createAnnotations,
  }, async ({ courseId, assignmentId, comment }) => {
    const profile = await client.request<{ id: string | number }>("GET", "/api/v1/users/self/profile");
    return result(await client.request("PUT", coursePath(courseId, `/assignments/${encodeURIComponent(assignmentId)}/submissions/${encodeURIComponent(String(profile.id))}`), { body: { comment: { text_comment: comment } } }));
  });

  server.registerTool("send_message", {
    description: "Send a Canvas Inbox message to explicit individual recipients. Course-wide and group-wide recipients are rejected.",
    inputSchema: { recipientIds: z.array(id).min(1).max(10), subject: z.string().min(1).max(255), body: z.string().min(1).max(100_000) }, annotations: createAnnotations,
  }, async ({ recipientIds, subject, body }) => {
    if (recipientIds.some(value => value.startsWith("course_") || value.startsWith("group_"))) throw new Error("Only explicit individual recipient IDs are allowed");
    return result(await client.request("POST", "/api/v1/conversations", { body: { recipients: recipientIds, subject, body, force_new: true } }));
  });

  server.registerTool("create_personal_calendar_event", {
    description: "Create an event only on the authenticated student's personal Canvas calendar.",
    inputSchema: { title: z.string().min(1).max(255), description: z.string().max(100_000).optional(), startAt: z.string().datetime(), endAt: z.string().datetime().optional(), locationName: z.string().max(255).optional() }, annotations: createAnnotations,
  }, async ({ title, description, startAt, endAt, locationName }) => {
    const profile = await client.request<{ id: string | number }>("GET", "/api/v1/users/self/profile");
    return result(await client.request("POST", "/api/v1/calendar_events", { body: { calendar_event: { context_code: `user_${profile.id}`, title, description, start_at: startAt, end_at: endAt, location_name: locationName } } }));
  });

  server.registerTool("edit_own_discussion_entry", {
    description: "Edit a discussion entry only after verifying it belongs to the authenticated user.",
    inputSchema: { courseId: id, topicId: id, entryId: id, message: z.string().min(1).max(200_000) }, annotations: updateAnnotations,
  }, async ({ courseId, topicId, entryId, message }) => {
    const [profile, entry] = await Promise.all([
      client.request<{ id: string | number }>("GET", "/api/v1/users/self/profile"),
      client.request<Array<{ user_id: string | number }>>("GET", coursePath(courseId, `/discussion_topics/${encodeURIComponent(topicId)}/entry_list`), { query: { "ids[]": [entryId] } }),
    ]);
    if (!entry[0] || String(entry[0].user_id) !== String(profile.id)) throw new Error("This discussion entry is not owned by the authenticated user");
    return result(await client.request("PUT", coursePath(courseId, `/discussion_topics/${encodeURIComponent(topicId)}/entries/${encodeURIComponent(entryId)}`), { body: { message } }));
  });

  server.registerTool("mark_module_item_complete", {
    description: "Mark a module item complete for the authenticated student.",
    inputSchema: { courseId: id, moduleId: id, itemId: id }, annotations: updateAnnotations,
  }, async ({ courseId, moduleId, itemId }) => result(await client.request("POST", coursePath(courseId, `/modules/${encodeURIComponent(moduleId)}/items/${encodeURIComponent(itemId)}/done`))));

  server.registerTool("mark_module_item_incomplete", {
    description: "Remove the authenticated student's completion marker from a module item; no course content is deleted.",
    inputSchema: { courseId: id, moduleId: id, itemId: id }, annotations: updateAnnotations,
  }, async ({ courseId, moduleId, itemId }) => result(await client.request("DELETE", coursePath(courseId, `/modules/${encodeURIComponent(moduleId)}/items/${encodeURIComponent(itemId)}/done`))));

  server.registerTool("update_conversation_state", {
    description: "Update read/archive state or starred status for one of the authenticated user's conversations.",
    inputSchema: { conversationId: id, workflowState: z.enum(["read", "unread", "archived"]).optional(), starred: z.boolean().optional() }, annotations: updateAnnotations,
  }, async ({ conversationId, workflowState, starred }) => {
    if (workflowState === undefined && starred === undefined) throw new Error("Provide workflowState or starred");
    return result(await client.request("PUT", `/api/v1/conversations/${encodeURIComponent(conversationId)}`, { body: { conversation: { workflow_state: workflowState, starred } } }));
  });

  server.registerTool("update_personal_calendar_event", {
    description: "Update a calendar event only after verifying it belongs to the authenticated user's personal calendar.",
    inputSchema: { eventId: id, title: z.string().min(1).max(255).optional(), description: z.string().max(100_000).optional(), startAt: z.string().datetime().optional(), endAt: z.string().datetime().optional(), locationName: z.string().max(255).optional() }, annotations: updateAnnotations,
  }, async ({ eventId, title, description, startAt, endAt, locationName }) => {
    const [profile, event] = await Promise.all([
      client.request<{ id: string | number }>("GET", "/api/v1/users/self/profile"),
      client.request<{ context_code: string }>("GET", `/api/v1/calendar_events/${encodeURIComponent(eventId)}`),
    ]);
    if (event.context_code !== `user_${profile.id}`) throw new Error("This event is not on the authenticated user's personal calendar");
    return result(await client.request("PUT", `/api/v1/calendar_events/${encodeURIComponent(eventId)}`, { body: { calendar_event: { title, description, start_at: startAt, end_at: endAt, location_name: locationName } } }));
  });

  return server;
}
