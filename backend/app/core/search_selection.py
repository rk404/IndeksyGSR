# Manage Checkbox Selection State for Search Results

class SearchSelection:
    def __init__(self):
        self.selected_items = set()

    def select_item(self, item_id):
        self.selected_items.add(item_id)

    def deselect_item(self, item_id):
        self.selected_items.discard(item_id)

    def is_selected(self, item_id):
        return item_id in self.selected_items

    def clear_selection(self):
        self.selected_items.clear()