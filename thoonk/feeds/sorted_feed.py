from thoonk.exceptions import *
from thoonk.feeds import *


class SortedFeed(Feed):

    """
    A Thoonk sorted feed is a manually ordered collection of items.

    Redis Keys Used:
        feed.idincr:[feed] -- A counter for ID values.

    Thoonk.py Implementation API:
        get_schemas -- Return the set of Redis keys used by this feed.

    Thoonk Standard API:
        append    -- Append an item to the end of the feed.
        edit      -- Edit an item in-place.
        get_all   -- Return all items in the feed.
        get_ids   -- Return the IDs of all items in the feed.
        get_item  -- Return a single item from the feed given its ID.
        prepend   -- Add an item to the beginning of the feed.
        retract   -- Remove an item from the feed.
        publish   -- Add an item to the end of the feed.
        publish_after  -- Add an item immediately before an existing item.
        publish_before -- Add an item immediately after an existing item.
    """

    def __init__(self, thoonk, feed, config=None):
        """
        Create a new SortedFeed object for a given Thoonk feed.

        Note: More than one SortedFeed objects may be create for the same
              Thoonk feed, and creating a SortedFeed object does not
              automatically generate the Thoonk feed itself.

        Arguments:
            thoonk -- The main Thoonk object.
            feed   -- The name of the feed.
            config -- Optional dictionary of configuration values.

        """
        Feed.__init__(self, thoonk, feed, config)

        self.feed_id_incr = 'feed.idincr:%s' % feed

    def get_schemas(self):
        """Return the set of Redis keys used exclusively by this feed."""
        schema = set((self.feed_id_incr,))
        return schema.union(Feed.get_schemas(self))

    def append(self, item):
        """
        Add an item to the end of the feed.

        (Same as publish)

        Arguments:
            item -- The item contents to add.
        """
        return self.publish(item)

    def prepend(self, item):
        """
        Add an item to the beginning of the feed.

        Arguments:
            item -- The item contents to add.
        """
        id = self.redis.incr(self.feed_id_incr)
        pipe = self.redis.pipeline()
        pipe.lpush(self.feed_ids, id)
        pipe.incr(self.feed_publishes)
        pipe.hset(self.feed_items, id, item)
        pipe.publish(self.feed_publish, '%s\x00%s' % (id, item))
        pipe.execute()
        return id

    def __insert(self, item, rel_id, method):
        """
        Insert an item into the feed, either before or after an
        existing item.

        Arguments:
            item   -- The item contents to insert.
            rel_id -- The ID of an existing item.
            method -- Either 'BEFORE' or 'AFTER', and indicates
                      where the item will be inserted in relation
                      to rel_id.
        """
        id = self.redis.incr(self.feed_id_incr)
        while True:
            self.redis.watch(self.feed_items)
            if not self.redis.hexists(self.feed_items, rel_id):
                self.redis.unwatch()
                return # raise exception?

            pipe = self.redis.pipeline()
            pipe.linsert(self.feed_ids, method, rel_id, id)
            pipe.hset(self.feed_items, id, item)
            pipe.publish(self.feed_publish, '%s\x00%s' % (id, item))

            try:
                pipe.execute()
                break
            except redis.exceptions.WatchError:
                pass
        return id

    def publish(self, item):
        """
        Add an item to the end of the feed.

        (Same as append)

        Arguments:
            item -- The item contens to add.
        """
        id = self.redis.incr(self.feed_id_incr)
        pipe = self.redis.pipeline()
        pipe.rpush(self.feed_ids, id)
        pipe.incr(self.feed_publishes)
        pipe.hset(self.feed_items, id, item)
        pipe.publish(self.feed_publish, '%s\x00%s' % (id, item))
        pipe.execute()
        return id

    def edit(self, id, item):
        """
        Modify an item in-place in the feed.

        Arguments:
            id   -- The ID value of the item to edit.
            item -- The new contents of the item.
        """
        while True:
            self.redis.watch(self.feed_items)
            if not self.redis.hexists(self.feed_items, id):
                self.redis.unwatch()
                return # raise exception?

            pipe = self.redis.pipeline()
            pipe.hset(self.feed_items, id, item)
            pipe.incr(self.feed_publishes)
            pipe.publish(self.feed_publish, '%s\x00%s' % (id, item))

            try:
                pipe.execute()
                break
            except redis.exceptions.WatchError:
                pass

    def publish_before(self, before_id, item):
        """
        Add an item immediately before an existing item.

        Arguments:
            before_id -- ID of the item to insert before.
            item      -- The item contents to add.
        """
        return self.__insert(item, before_id, 'BEFORE')

    def publish_after(self, after_id, item):
        """
        Add an item immediately after an existing item.

        Arguments:
            after_id -- ID of the item to insert after.
            item     -- The item contents to add.
        """
        return self.__insert(item, after_id, 'AFTER')

    def retract(self, id):
        """
        Remove an item from the feed.

        Arguments:
            id -- The ID value of the item to remove.
        """
        while True:
            self.redis.watch(self.feed_items)
            if self.redis.hexists(self.feed_items, id):
                pipe = self.redis.pipeline()
                pipe.lrem(self.feed_ids, id, 1)
                pipe.hdel(self.feed_items, id)
                pipe.publish(self.feed_retract, id)
                try:
                    pipe.execute()
                    break
                except redis.exceptions.WatchError:
                    pass
            else:
                self.redis.unwatch()
                return

    def get_ids(self):
        """Return the set of IDs used by items in the feed."""
        return self.redis.lrange(self.feed_ids, 0, -1)

    def get_item(self, id):
        """
        Retrieve a single item from the feed.

        Arguments:
            id -- The ID of the item to retrieve.
        """
        return self.redis.hget(self.feed_items, id)

    def get_items(self):
        """Return all items from the feed."""
        return self.redis.hgetall(self.feed_items)
