"""Defintion of the TinyFlux Index.

Class descriptions for Index and IndexResult.  An Index acts like a singleton,
and is initialized at creation time with the TinyFlux instance. It provides
efficient in-memory data structures and getters for TinyFlux operations. An
Index instance is not a part of the TinyFlux interface.

An IndexResult returns the indicies of revelant TinyFlux queries for further
handling, usually as an input to a storage retrieval.
"""
from datetime import datetime
import operator
from typing import List, Optional, Set, Union
from xxlimited import new

from tinyflux.queries import SimpleQuery, CompoundQuery
from .point import Point
from .utils import (
    find_eq,
    find_lt,
    find_le,
    find_gt,
    find_ge,
    difference_generator_and_sorted_lists,
    intersection_two_sorted_lists,
    union_two_sorted_lists,
)


class IndexResult:
    """Returns indicies of TinyFlux queries that are handled by an Index.

    IndexResults instances are generated by an Index.

    Arritributes:
        items: A list of indicies as ints.
        is_complete: A boolean indicating if the query is complete or needs to
            be passed onto the storage layer for further querying.

    Usage:
        >>> IndexResult(items=list(), is_complete=True, index_count=0)
    """

    def __init__(self, items: Set[int], is_complete: bool, index_count: int):
        """Init IndexResult.

        Args:
            items: Matching items from a query as indicies.
            is_complete: Items should be passed to another search.
            index_count: Number of items in the index..
        """
        self._items = items
        self._is_complete = is_complete
        self._index_count = index_count

    @property
    def items(self):
        """Return query result items."""
        return self._items

    @property
    def is_complete(self):
        """Return whether query is complete or needs to be passed along."""
        return self._is_complete

    def __invert__(self) -> "IndexResult":
        """Return the complement list.

        Returns:
            An IndexResult in which the items are the complement.

        Usage:
            >>> ~IndexResult()
        """
        # Invert items.
        # new_items = set({})
        # for i in range(self._index_count):
        #     if i not in self._items:
        #         new_items.add(i)

        return IndexResult(
            difference_generator_and_sorted_lists(
                range(self._index_count), self._items
            ),
            self._is_complete,
            self._index_count,
        )

    def __and__(self, other: "IndexResult") -> "IndexResult":
        """Return the intersection of two IndexResults as one IndexResult.

        Args:
            other: Another IndexResult.

        Returns:
            An IndexResult in which the items are the intersection.

        Usage:
            >>> IndexResult() & IndexResult()
        """
        return IndexResult(
            intersection_two_sorted_lists(self._items, other._items),
            self._is_complete and other._is_complete,
            self._index_count,
        )

    def __or__(self, other: "IndexResult") -> "IndexResult":
        """Return the union of two IndexResults as one IndexResult.

        Args:
            other: Another IndexResult.

        Returns:
            An IndexResult in which the items are the union.

        Usage:
            >>> IndexResult() | IndexResult()
        """
        return IndexResult(
            union_two_sorted_lists(self._items, other._items),
            self._is_complete and other._is_complete,
            self._index_count,
        )


class Index:
    """An in-memory index for the storage instance.

    Provides efficient data structures and searches for TinyFlux data. An Index
    instance is created and its lifetime is handled by a TinyFlux instance.

    Arritributes:
        empty: Index contains no items (used in testing).
        valid: Index represents current state of TinyFlux.

    Todo:
        switch from sets to lists.
    """

    def __init__(self, valid: bool = True) -> None:
        """Initialize an Index.

        Accepts a list of Points sorted by time.

        Args:
            valid: Index represents current state of TinyFlux.
        """
        self._num_items: int = 0
        self._tags: dict[str, dict[str, list]] = {}
        self._fields: dict[str, list] = {}
        self._measurements: dict[str, list] = {}
        self._timestamps: List[datetime] = []
        self._valid: bool = valid

    @property
    def empty(self) -> bool:
        """Return True if index is empty."""
        return (
            not self._num_items
            and not self._tags
            and not self._fields
            and not self._measurements
            and not self._timestamps
        )

    @property
    def valid(self) -> bool:
        """Return an empty index."""
        return self._valid

    def __len__(self) -> int:
        """Return number of items in the index."""
        return self._num_items

    def __repr__(self) -> str:
        """Return printable representation of Index."""
        args = [
            f"_tags={len(self._tags.keys())}",
            f"_measurements={len(self._measurements.keys())}",
            f"_timestamps={len(self._timestamps)}",
        ]

        return f'<{type(self).__name__} {", ".join(args)}>'

    def build(self, points: List[Point] = []) -> None:
        """Build the index from scratch.

        Args:
            points: The collection of points to build the Index from.

        Usage:
            >>> i = Index().build([Point()])
        """
        self._reset()

        for idx, point in enumerate(points):
            self._num_items += 1
            self._insert_time(point.time)
            self._insert_tags(idx, point.tags)
            self._insert_fields(idx, point.fields)
            self._insert_measurements(idx, point.measurement)

        return

    def get_measurement_names(self) -> set:
        """Get the names of all measurements in the Index.

        Returns:
            Unique names of measurements as a set.

        Usage:
            >>> n = Index().build([Point()]).get_measurement_names()
        """
        return set(self._measurements.keys())

    def insert(self, points: List[Point] = []) -> None:
        """Update index with new points.

        Accepts new points to add to an Index.  Points are assumed to be passed
        to this method in non-descending time order.

        Args:
            points: List of tinyflux.Point instances.

        Usage:
            >>> Index().insert([Point()])
        """
        start_idx = len(self._timestamps)

        for idx, point in enumerate(points):
            new_idx = start_idx + idx

            self._num_items += 1
            self._insert_time(point.time)
            self._insert_tags(new_idx, point.tags)
            self._insert_fields(new_idx, point.fields)
            self._insert_measurements(new_idx, point.measurement)

        return

    def invalidate(self):
        """Invalidate an Index.

        This method is invoked when the Index no longer represents the
        current state of TinyFlux and its Storage instance.

        Usage:
            >>> i = Index()
            >>> i.invalidate()
        """
        # Empty out the index.
        self._reset()

        # Set 'valid' to False.
        self._valid = False

        return

    def remove(self, r_items: Set[int]) -> None:
        """Remove items from the index."""
        self._remove_timestamps(r_items)
        self._remove_measurements(r_items)
        self._remove_tags(r_items)
        self._remove_fields(r_items)
        self._num_items -= len(r_items)

        return

    def search(self, query: Union[CompoundQuery, SimpleQuery]) -> IndexResult:
        """Handle a TinyFlux query.

        Parses the query, generates a new IndexResult, and returns it.

        Args:
            query: A tinyflux.queries.SimpleQuery.

        Returns:
            An IndexResult instance.

        Usage:
            >>> i = Index().build([Point()])
            >>> q = TimeQuery() < datetime.utcnow()
            >>> r = i.search(q)
        """
        return self._search_helper(query)

    def update(self, u_items: dict[int, int]) -> None:
        """ """
        self._update_measurements(u_items)
        self._update_tags(u_items)
        self._update_fields(u_items)

        return

    def _insert_fields(self, idx: int, fields: dict[str, str]) -> None:
        """Index a field value.

        Args:
            idx: Index of the point.
            fields: Dict of Field key/vals.
        """
        for field_key in fields.keys():

            if field_key not in self._fields:
                self._fields[field_key] = [idx]
            else:
                self._fields[field_key].append(idx)

        return

    def _insert_measurements(self, idx: int, measurement: str) -> None:
        """Index a measurement value.

        Args:
            idx: Index of the point.
            measurement: Name of measurement.
        """
        if measurement not in self._measurements:
            self._measurements[measurement] = [idx]
        else:
            self._measurements[measurement].append(idx)

        return

    def _insert_tags(self, idx: int, tags: dict[str, str]) -> None:
        """Index a tag value.

        Args:
            idx: Index of the point.
            tags: Dict of Tag key/vals.
        """
        for tag_key, tag_value in tags.items():

            if tag_key not in self._tags:
                self._tags[tag_key] = {}

            if tag_value not in self._tags[tag_key]:
                self._tags[tag_key][tag_value] = [idx]
            else:
                self._tags[tag_key][tag_value].append(idx)

        return

    def _insert_time(self, time: datetime) -> None:
        """Index a time value.

        Args:
            time: Time to index.
        """
        self._timestamps.append(time.timestamp())

        return

    def _reset(self) -> None:
        """Reset the index.

        Empty the index out.
        """
        self._num_items = 0
        self._tags = {}
        self._fields = {}
        self._measurements = {}
        self._timestamps = []

        self._valid = True

        return

    def _search_fields(self, query: SimpleQuery) -> Set[int]:
        """Search the index for field matches.

        A field value is never indexed, so this search returns a list of
        candidates by index.  This list will then be passed onto the storage
        layer for full evaluation.

        Args:
            query: A SimpleQuery instance.

        Returns:
            A list of candidates by index value.
        """
        rst_items = []

        for field_key, items in self._fields.items():
            # Transform the key.
            try:
                query._path_resolver({field_key: ""})
            except:
                continue

            rst_items = union_two_sorted_lists(rst_items, items)

            continue

        return rst_items

    def _search_helper(
        self, query: Optional[Union[CompoundQuery, SimpleQuery]]
    ) -> IndexResult:
        """Return an IndexResult from a parsed query.

        This method is recursive in order to handle compound queries.

        Args:
            query: A CompoundQuert or SimpleQuery.

        Returns:
            An IndexResult instance.
        """
        if isinstance(query, CompoundQuery):
            if query.operator == operator.and_:
                rst1 = self._search_helper(query.query1)
                rst2 = self._search_helper(query.query2)
                return rst1 & rst2

            if query.operator == operator.or_:
                rst1 = self._search_helper(query.query1)
                rst2 = self._search_helper(query.query2)
                return rst1 | rst2

            if query.operator == operator.not_:
                rst = self._search_helper(query.query1)

                # For logical-NOT with a FieldQuery, we have to check every
                # single item in storage :(
                if (
                    isinstance(query.query1, SimpleQuery)
                    and query.query1._point_attr == "_fields"
                ):
                    rst._items = list(range(self._num_items))
                    return rst
                else:
                    return ~rst

        if isinstance(query, SimpleQuery):
            if query.point_attr == "_time":
                return IndexResult(
                    self._search_timestamps(query), True, self._num_items
                )

            if query.point_attr == "_measurement":
                return IndexResult(
                    self._search_measurement(query), True, self._num_items
                )

            if query.point_attr == "_tags":
                return IndexResult(
                    self._search_tags(query), True, self._num_items
                )

            if query.point_attr == "_fields":
                return IndexResult(
                    self._search_fields(query), False, self._num_items
                )

        raise TypeError("Query must be SimpleQuery or CompoundQuery.")

    def _search_measurement(self, query: SimpleQuery) -> list:
        """Search the index for measurement matches.

        Args:
            query: A SimpleQuery instance.

        Returns:
            A list of matches by index value.
        """
        rst_items = []

        for key, items in self._measurements.items():
            # Transform the key.
            test_value = query._path_resolver(key)

            # If it matches, update the list.
            if query._test(test_value):
                rst_items = union_two_sorted_lists(rst_items, items)

        return rst_items

    def _search_tags(self, query: SimpleQuery) -> list:
        """Search the index for tag matches.

        Args:
            query: A SimpleQuery instance.

        Returns:
            A list of matches as index values.
        """
        rst_items = []

        for tag_key, tag_values in self._tags.items():
            for value, items in tag_values.items():
                # Transform the key.
                try:
                    test_value = query._path_resolver({tag_key: value})
                except:
                    continue

                # If it matches, update the list.
                if query._test(test_value):
                    rst_items = union_two_sorted_lists(rst_items, items)

        return rst_items

    def _search_timestamps(self, query) -> list:
        """Search for a timestamp.

        Search function for searching the timestamp index.

        Args:
            func: The operator or test of a query.
            rhs: The right-hand-side of the operator.

        Returns:
            A list of matches as a list of indices.
        """
        op = query._operator
        rhs = query._rhs

        # Exact timestamp match.
        if op == operator.eq:

            match = find_eq(self._timestamps, rhs.timestamp())
            if match is None:
                return []

            results = [match]

            match += 1

            while match < len(self._timestamps):
                if self._timestamps[match] != rhs.timestamp():
                    break

                results.append(match)
                match += 1

            return results

        # Anything except exact timestamp match.
        elif op == operator.ne:

            match = find_eq(self._timestamps, rhs.timestamp())
            if match is None:
                return list(range(len(self._timestamps)))

            results = [match]

            match += 1

            while match < len(self._timestamps):
                if self._timestamps[match] != rhs.timestamp():
                    break

                results.append(match)
                match += 1

            return difference_generator_and_sorted_lists(
                range(len(self._timestamps)), results
            )

        # Everything less than rhs.
        elif op == operator.lt:

            match = find_lt(self._timestamps, rhs.timestamp())

            if match is None:
                return []

            return list(range(match + 1))

        # Every less than or equal to rhs.
        elif op == operator.le:
            match = find_le(self._timestamps, rhs.timestamp())

            if match is None:
                return []

            return list(range(match + 1))

        # Everything greater than rhs.
        elif op == operator.gt:
            match = find_gt(self._timestamps, rhs.timestamp())

            if match is None:
                return []

            return list(range(match, len(self._timestamps)))

        # Everything greater than or equal to rhs.
        elif op == operator.ge:
            match = find_ge(self._timestamps, rhs.timestamp())

            if match is None:
                return []

            return list(range(match, len(self._timestamps)))

        # All other operators.
        else:
            items = []
            for idx, timestamp in enumerate(self._timestamps):
                if query._test(
                    query._path_resolver(datetime.fromtimestamp(timestamp))
                ):
                    items.append(idx)

            return items

    def _remove_fields(self, r_items):
        """"""
        new_fields = {}

        for field_key, old_items in self._fields.items():
            new_items = [i for i in old_items if i not in r_items]
            if new_items:
                new_fields[field_key] = new_items

        self._fields = new_fields

        return

    def _remove_measurements(self, r_items):
        """ """
        new_measurements = {}

        for m in self._measurements.keys():
            new_items = [i for i in self._measurements[m] if i not in r_items]
            if new_items:
                new_measurements[m] = new_items

        self._measurements = new_measurements

        return

    def _remove_tags(self, r_items):
        """"""
        new_tags = {}

        for tag_key, tag_values in self._tags.items():
            for value, old_items in tag_values.items():
                new_items = [i for i in old_items if i not in r_items]

                if not new_items:
                    continue

                if tag_key not in new_tags:
                    new_tags[tag_key] = {value: new_items}
                else:
                    new_tags[tag_key][value] = new_items

        self._tags = new_tags

        return

    def _remove_timestamps(self, r_items):
        """ """
        new_timestamps = []

        for i, ts in enumerate(self._timestamps):
            if i not in r_items:
                new_timestamps.append(ts)

        self._timestamps = new_timestamps

        return

    def _update_fields(self, u_items):
        """"""
        for field_key, old_items in self._fields.items():
            updated_items = []
            for i in old_items:
                updated_items.append(u_items[i])
            self._fields[field_key] = updated_items

        return

    def _update_measurements(self, u_items):
        """ """
        new_measurements = {}

        for m in self._measurements.keys():
            updated_items = []

            for i in self._measurements[m]:
                updated_items.append(u_items[i])

            if updated_items:
                new_measurements[m] = updated_items

        self._measurements = new_measurements

        return

    def _update_tags(self, u_items):
        """"""
        for tag_key, tag_values in self._tags.items():
            for value, old_items in tag_values.items():
                updated_items = []
                for i in old_items:
                    updated_items.append(u_items[i])
                self._tags[tag_key][value] = updated_items

        return
