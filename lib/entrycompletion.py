#!/usr/bin/env python

import gtk, guiplugins

class EntryCompletionManager:
    def __init__(self):
        self.completions = gtk.ListStore(str)
        self.entries = []
        self.enabled = False
        
    def start(self):
        self.matching = guiplugins.guiConfig.getValue("gui_entry_completion_matching")
        if self.matching != 0:
            self.enabled = True
            guiplugins.guilog.info("Enabling entry completion, using matching " + str(self.matching))

            completions = guiplugins.guiConfig.getCompositeValue("gui_entry_completions", "", modeDependent=True)
            for completion in completions:
                self.addTextCompletion(completion)
            
    def register(self, entry):
        if self.enabled:
            completion = gtk.EntryCompletion()
            completion.set_model(self.completions)
            completion.set_text_column(0)        
            if self.matching == 2: # Matching on start is default for gtk.EntryCompletion
                completion.set_match_func(self.containsMatchFunction)        

            self.addCompletion(entry)
            entry.set_completion(completion)
            entry.connect('activate', self.addCompletion)
            self.entries.append(entry)

    def addCompletion(self, entry):
        self.addTextCompletion(entry.get_text())

    def addTextCompletion(self, text):
        if self.enabled and text and text not in [row[0] for row in self.completions]:
            guiplugins.guilog.info("Adding entry completion " + repr(text).replace("\\", "/") + " ...")
            self.completions.append([text])            

    def collectCompletions(self):
        if self.enabled:
            for entry in self.entries:
                self.addCompletion(entry)

    # Return true for any completion containing the key
    def containsMatchFunction(self, completion, key_string, iter):
        value = self.completions.get_value(iter, 0)
        return value and value.lower().find(key_string) != -1
    
manager = EntryCompletionManager()
