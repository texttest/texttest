#!/usr/bin/env python

from gi.repository import Gtk


class EntryCompletionManager:
    def __init__(self):
        self.completions = Gtk.ListStore(str)
        self.entries = []
        self.enabled = False
        self.useContainsFunction = False
        self.inlineCompletions = False

    def start(self, matching, inline, completions):
        self.enabled = True
        self.useContainsFunction = matching == 2
        self.inlineCompletions = inline

        for completion in completions:
            self.addTextCompletion(completion)

    def register(self, entry):
        if self.enabled:
            completion = Gtk.EntryCompletion()
            completion.set_model(self.completions)
            if self.inlineCompletions:
                completion.set_inline_completion(True)
            completion.set_text_column(0)
            if self.useContainsFunction:  # Matching on start is default for Gtk.EntryCompletion
                completion.set_match_func(self.containsMatchFunction)

            self.addCompletion(entry)
            entry.set_completion(completion)
            entry.connect('activate', self.addCompletion)
            self.entries.append(entry)

    def addCompletion(self, entry):
        self.addTextCompletion(entry.get_text())

    def addTextCompletion(self, text):
        if self.enabled and text and text not in [row[0] for row in self.completions]:
            self.completions.prepend([text])

    def collectCompletions(self):
        if self.enabled:
            for entry in self.entries:
                self.addCompletion(entry)

    # Return true for any completion containing the key
    def containsMatchFunction(self, dummy, key_string, iter):
        value = self.completions.get_value(iter, 0)
        return value and value.lower().find(key_string) != -1


manager = EntryCompletionManager()
