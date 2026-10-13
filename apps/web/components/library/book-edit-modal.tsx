/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { InputField } from "@makeplane/propel/components/input-field";
import { TextAreaField } from "@makeplane/propel/components/text-area-field";
import { setToast } from "@plane/blocks/toast";
import type { TBook, TBookUpdatePayload } from "@plane/types";
// hooks
import { useLibrary } from "@/hooks/store/use-library";
import { libraryErrorMessage } from "@/store/library.store";

type Props = {
  workspaceSlug: string;
  book: TBook;
  isOpen: boolean;
  onClose: () => void;
};

const splitList = (value: string, separator: RegExp) =>
  value
    .split(separator)
    .map((item) => item.trim())
    .filter(Boolean);

/** Edit a book's details and tags. Edited details are kept when the book is processed again. */
export const BookEditModal = observer(function BookEditModal({ workspaceSlug, book, isOpen, onClose }: Props) {
  const { updateBook } = useLibrary();
  const [form, setForm] = useState({
    title: "",
    authors: "",
    publisher: "",
    language: "",
    isbn: "",
    published_date: "",
    description: "",
    tags: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setForm({
      title: book.title,
      authors: book.authors.join("\n"),
      publisher: book.publisher,
      language: book.language,
      isbn: book.isbn,
      published_date: book.published_date,
      description: book.description,
      tags: book.tags.join(", "),
    });
    setErrors({});
  }, [book, isOpen]);

  const field = (name: keyof typeof form) => ({
    value: form[name],
    onChange: (e: { target: { value: string } }) => setForm((current) => ({ ...current, [name]: e.target.value })),
    error: errors[name],
  });

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrors({});
    const payload: TBookUpdatePayload = {
      title: form.title.trim(),
      authors: splitList(form.authors, /\n/),
      publisher: form.publisher,
      language: form.language,
      isbn: form.isbn,
      published_date: form.published_date,
      description: form.description,
      tags: splitList(form.tags, /,/),
    };
    try {
      await updateBook(workspaceSlug, book.id, payload);
      setToast({ type: "success", title: "Saved", message: "The book's details were updated." });
      onClose();
    } catch (error) {
      const fieldErrors = Object.fromEntries(
        Object.entries((error ?? {}) as Record<string, unknown>)
          .filter(([, value]) => Array.isArray(value))
          .map(([key, value]) => [key, String((value as string[])[0])])
      );
      setErrors(fieldErrors);
      if (!Object.keys(fieldErrors).length)
        setToast({
          type: "error",
          title: "Error!",
          message: libraryErrorMessage(error, "The book could not be saved."),
        });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="lg">
        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          <DialogMain>
            <DialogHeader>
              <DialogHeading>
                <DialogTitle>Edit book details</DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <InputField
                    id="book-title"
                    label="Title"
                    size="md"
                    orientation="vertical"
                    required
                    {...field("title")}
                  />
                </div>
                <TextAreaField
                  id="book-authors"
                  label="Authors"
                  size="lg"
                  resize="none"
                  autoResize
                  maxRows={5}
                  description="One per line."
                  {...field("authors")}
                />
                <InputField
                  id="book-tags"
                  label="Tags"
                  size="md"
                  orientation="vertical"
                  placeholder="e.g. Air law, Drones"
                  description="Separate tags with commas."
                  {...field("tags")}
                />
                <InputField
                  id="book-publisher"
                  label="Publisher"
                  size="md"
                  orientation="vertical"
                  {...field("publisher")}
                />
                <InputField
                  id="book-published"
                  label="Published"
                  size="md"
                  orientation="vertical"
                  placeholder="e.g. 2026-10-29"
                  {...field("published_date")}
                />
                <InputField
                  id="book-language"
                  label="Language"
                  size="md"
                  orientation="vertical"
                  placeholder="e.g. en"
                  {...field("language")}
                />
                <InputField id="book-isbn" label="ISBN" size="md" orientation="vertical" {...field("isbn")} />
                <div className="sm:col-span-2">
                  <TextAreaField
                    id="book-description"
                    label="Description"
                    size="lg"
                    resize="vertical"
                    autoResize
                    maxRows={10}
                    {...field("description")}
                  />
                </div>
              </div>
            </DialogBody>
          </DialogMain>
          <DialogActions>
            <Button stretch="auto" variant="secondary" size="md" label="Cancel" onClick={onClose} type="button" />
            <Button
              stretch="auto"
              variant="primary"
              size="md"
              type="submit"
              label={isSubmitting ? "Saving…" : "Save"}
              disabled={isSubmitting || !form.title.trim()}
            />
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
});
