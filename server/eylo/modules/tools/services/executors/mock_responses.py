"""Application services for the `tools` domain."""

MRM_TOOL_RESPONSES = {
    "create_booking": {
        "booking_id": 910001,
    },
    "list_available_rooms": [
        {
            "id": 7601,
            "parent_id": 7478,
            "name": "Aurora Meeting Room",
            "description": None,
            "type": 2,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "room",
            "amenities": [
                {
                    "id": 125,
                    "quantity": 1,
                    "amenity__label": "Desktop",
                    "amenity__icon": "Desktop",
                },
                {
                    "id": 126,
                    "quantity": 1,
                    "amenity__label": "Mouse and Keyboard",
                    "amenity__icon": "Keyboard & Mouse",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7478,
                    "name": "First Floor",
                    "type": 6,
                    "parent_id": 7476,
                },
                {
                    "id": 7476,
                    "name": "Meridian Towers",
                    "type": 5,
                    "parent_id": 7475,
                },
                {
                    "id": 7475,
                    "name": "Acme R&D Center - Springfield",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7602,
            "parent_id": 7477,
            "name": "Orion Conference Room",
            "description": None,
            "type": 2,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "room",
            "amenities": [
                {
                    "id": 125,
                    "quantity": 1,
                    "amenity__label": "Desktop",
                    "amenity__icon": "Desktop",
                },
                {
                    "id": 127,
                    "quantity": 1,
                    "amenity__label": "Projector",
                    "amenity__icon": "Projector",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7477,
                    "name": "Second Floor",
                    "type": 6,
                    "parent_id": 7476,
                },
                {
                    "id": 7476,
                    "name": "Meridian Towers",
                    "type": 5,
                    "parent_id": 7475,
                },
                {
                    "id": 7475,
                    "name": "Acme R&D Center - Springfield",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7603,
            "parent_id": 7483,
            "name": "Nexus Board Room",
            "description": None,
            "type": 2,
            "tags": [
                {
                    "id": 401,
                    "name": "Executive",
                    "description": "Executive",
                }
            ],
            "venue_type": "room",
            "amenities": [
                {
                    "id": 129,
                    "quantity": 1,
                    "amenity__label": "Video Conferencing",
                    "amenity__icon": "Video",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
                {
                    "id": 131,
                    "quantity": 1,
                    "amenity__label": "Whiteboard",
                    "amenity__icon": "Whiteboard",
                },
            ],
            "ancestors": [
                {
                    "id": 7483,
                    "name": "First Floor",
                    "type": 6,
                    "parent_id": 7482,
                },
                {
                    "id": 7482,
                    "name": "Harbor Tower",
                    "type": 5,
                    "parent_id": 7481,
                },
                {
                    "id": 7481,
                    "name": "Acme East Office - Rivertown",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7604,
            "parent_id": 7484,
            "name": "Skyline Collaboration Room",
            "description": None,
            "type": 2,
            "tags": [
                {
                    "id": 401,
                    "name": "Executive",
                    "description": "Executive",
                }
            ],
            "venue_type": "room",
            "amenities": [
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
                {
                    "id": 132,
                    "quantity": 1,
                    "amenity__label": "Telepresence",
                    "amenity__icon": "Telepresence",
                },
                {
                    "id": 131,
                    "quantity": 1,
                    "amenity__label": "Whiteboard",
                    "amenity__icon": "Whiteboard",
                },
            ],
            "ancestors": [
                {
                    "id": 7484,
                    "name": "Second Floor",
                    "type": 6,
                    "parent_id": 7482,
                },
                {
                    "id": 7482,
                    "name": "Harbor Tower",
                    "type": 5,
                    "parent_id": 7481,
                },
                {
                    "id": 7481,
                    "name": "Acme East Office - Rivertown",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7605,
            "parent_id": 3572,
            "name": "Harbor Strategy Room",
            "description": None,
            "type": 2,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "room",
            "amenities": [
                {
                    "id": 125,
                    "quantity": 1,
                    "amenity__label": "Desktop",
                    "amenity__icon": "Desktop",
                },
                {
                    "id": 131,
                    "quantity": 1,
                    "amenity__label": "Whiteboard",
                    "amenity__icon": "Whiteboard",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 3572,
                    "name": "First Floor",
                    "type": 6,
                    "parent_id": 3571,
                },
                {
                    "id": 3571,
                    "name": "Success Towers",
                    "type": 5,
                    "parent_id": 3570,
                },
                {
                    "id": 3570,
                    "name": "Acme HQ Campus - Lakeside",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7606,
            "parent_id": 7480,
            "name": "Summit Innovation Room",
            "description": None,
            "type": 2,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "room",
            "amenities": [
                {
                    "id": 129,
                    "quantity": 1,
                    "amenity__label": "Video Conferencing",
                    "amenity__icon": "Video",
                },
                {
                    "id": 127,
                    "quantity": 1,
                    "amenity__label": "Projector",
                    "amenity__icon": "Projector",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7480,
                    "name": "Second Floor",
                    "type": 6,
                    "parent_id": 3571,
                },
                {
                    "id": 3571,
                    "name": "Success Towers",
                    "type": 5,
                    "parent_id": 3570,
                },
                {
                    "id": 3570,
                    "name": "Acme HQ Campus - Lakeside",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
    ],
    "list_available_desks": [
        {
            "id": 7701,
            "parent_id": 7478,
            "name": "Desk 100",
            "description": None,
            "type": 3,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "desk",
            "amenities": [
                {
                    "id": 125,
                    "quantity": 1,
                    "amenity__label": "Desktop",
                    "amenity__icon": "Desktop",
                },
                {
                    "id": 126,
                    "quantity": 1,
                    "amenity__label": "Mouse and Keyboard",
                    "amenity__icon": "Keyboard & Mouse",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7478,
                    "name": "First Floor",
                    "type": 6,
                    "parent_id": 7476,
                },
                {
                    "id": 7476,
                    "name": "Meridian Towers",
                    "type": 5,
                    "parent_id": 7475,
                },
                {
                    "id": 7475,
                    "name": "Acme R&D Center - Springfield",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7702,
            "parent_id": 7479,
            "name": "Desk 112",
            "description": None,
            "type": 3,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "desk",
            "amenities": [
                {
                    "id": 125,
                    "quantity": 1,
                    "amenity__label": "Desktop",
                    "amenity__icon": "Desktop",
                },
                {
                    "id": 133,
                    "quantity": 1,
                    "amenity__label": "Dual Monitors",
                    "amenity__icon": "Monitor",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7479,
                    "name": "Basement",
                    "type": 6,
                    "parent_id": 7476,
                },
                {
                    "id": 7476,
                    "name": "Meridian Towers",
                    "type": 5,
                    "parent_id": 7475,
                },
                {
                    "id": 7475,
                    "name": "Acme R&D Center - Springfield",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7703,
            "parent_id": 7483,
            "name": "Desk 210",
            "description": None,
            "type": 3,
            "tags": [
                {
                    "id": 401,
                    "name": "Executive",
                    "description": "Executive",
                }
            ],
            "venue_type": "desk",
            "amenities": [
                {
                    "id": 126,
                    "quantity": 1,
                    "amenity__label": "Mouse and Keyboard",
                    "amenity__icon": "Keyboard & Mouse",
                },
                {
                    "id": 133,
                    "quantity": 1,
                    "amenity__label": "Dual Monitors",
                    "amenity__icon": "Monitor",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7483,
                    "name": "First Floor",
                    "type": 6,
                    "parent_id": 7482,
                },
                {
                    "id": 7482,
                    "name": "Harbor Tower",
                    "type": 5,
                    "parent_id": 7481,
                },
                {
                    "id": 7481,
                    "name": "Acme East Office - Rivertown",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7704,
            "parent_id": 7484,
            "name": "Desk 318",
            "description": None,
            "type": 3,
            "tags": [
                {
                    "id": 401,
                    "name": "Executive",
                    "description": "Executive",
                }
            ],
            "venue_type": "desk",
            "amenities": [
                {
                    "id": 126,
                    "quantity": 1,
                    "amenity__label": "Mouse and Keyboard",
                    "amenity__icon": "Keyboard & Mouse",
                },
                {
                    "id": 131,
                    "quantity": 1,
                    "amenity__label": "Whiteboard",
                    "amenity__icon": "Whiteboard",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7484,
                    "name": "Second Floor",
                    "type": 6,
                    "parent_id": 7482,
                },
                {
                    "id": 7482,
                    "name": "Harbor Tower",
                    "type": 5,
                    "parent_id": 7481,
                },
                {
                    "id": 7481,
                    "name": "Acme East Office - Rivertown",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7705,
            "parent_id": 3572,
            "name": "Desk 421",
            "description": None,
            "type": 3,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "desk",
            "amenities": [
                {
                    "id": 125,
                    "quantity": 1,
                    "amenity__label": "Desktop",
                    "amenity__icon": "Desktop",
                },
                {
                    "id": 126,
                    "quantity": 1,
                    "amenity__label": "Mouse and Keyboard",
                    "amenity__icon": "Keyboard & Mouse",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 3572,
                    "name": "First Floor",
                    "type": 6,
                    "parent_id": 3571,
                },
                {
                    "id": 3571,
                    "name": "Success Towers",
                    "type": 5,
                    "parent_id": 3570,
                },
                {
                    "id": 3570,
                    "name": "Acme HQ Campus - Lakeside",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7706,
            "parent_id": 6598,
            "name": "Desk 538",
            "description": None,
            "type": 3,
            "tags": [
                {
                    "id": 401,
                    "name": "Executive",
                    "description": "Executive",
                }
            ],
            "venue_type": "desk",
            "amenities": [
                {
                    "id": 133,
                    "quantity": 1,
                    "amenity__label": "Dual Monitors",
                    "amenity__icon": "Monitor",
                },
                {
                    "id": 131,
                    "quantity": 1,
                    "amenity__label": "Whiteboard",
                    "amenity__icon": "Whiteboard",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 6598,
                    "name": "Third Floor",
                    "type": 6,
                    "parent_id": 3571,
                },
                {
                    "id": 3571,
                    "name": "Success Towers",
                    "type": 5,
                    "parent_id": 3570,
                },
                {
                    "id": 3570,
                    "name": "Acme HQ Campus - Lakeside",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
    ],
    "list_available_resources": [
        {
            "id": 7601,
            "parent_id": 7478,
            "name": "Aurora Meeting Room",
            "description": None,
            "type": 2,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "room",
            "amenities": [
                {
                    "id": 125,
                    "quantity": 1,
                    "amenity__label": "Desktop",
                    "amenity__icon": "Desktop",
                },
                {
                    "id": 126,
                    "quantity": 1,
                    "amenity__label": "Mouse and Keyboard",
                    "amenity__icon": "Keyboard & Mouse",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7478,
                    "name": "First Floor",
                    "type": 6,
                    "parent_id": 7476,
                },
                {
                    "id": 7476,
                    "name": "Meridian Towers",
                    "type": 5,
                    "parent_id": 7475,
                },
                {
                    "id": 7475,
                    "name": "Acme R&D Center - Springfield",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7602,
            "parent_id": 7477,
            "name": "Orion Conference Room",
            "description": None,
            "type": 2,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "room",
            "amenities": [
                {
                    "id": 125,
                    "quantity": 1,
                    "amenity__label": "Desktop",
                    "amenity__icon": "Desktop",
                },
                {
                    "id": 127,
                    "quantity": 1,
                    "amenity__label": "Projector",
                    "amenity__icon": "Projector",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7477,
                    "name": "Second Floor",
                    "type": 6,
                    "parent_id": 7476,
                },
                {
                    "id": 7476,
                    "name": "Meridian Towers",
                    "type": 5,
                    "parent_id": 7475,
                },
                {
                    "id": 7475,
                    "name": "Acme R&D Center - Springfield",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7603,
            "parent_id": 7483,
            "name": "Nexus Board Room",
            "description": None,
            "type": 2,
            "tags": [
                {
                    "id": 401,
                    "name": "Executive",
                    "description": "Executive",
                }
            ],
            "venue_type": "room",
            "amenities": [
                {
                    "id": 129,
                    "quantity": 1,
                    "amenity__label": "Video Conferencing",
                    "amenity__icon": "Video",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
                {
                    "id": 131,
                    "quantity": 1,
                    "amenity__label": "Whiteboard",
                    "amenity__icon": "Whiteboard",
                },
            ],
            "ancestors": [
                {
                    "id": 7483,
                    "name": "First Floor",
                    "type": 6,
                    "parent_id": 7482,
                },
                {
                    "id": 7482,
                    "name": "Harbor Tower",
                    "type": 5,
                    "parent_id": 7481,
                },
                {
                    "id": 7481,
                    "name": "Acme East Office - Rivertown",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7701,
            "parent_id": 7478,
            "name": "Desk 100",
            "description": None,
            "type": 3,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "desk",
            "amenities": [
                {
                    "id": 125,
                    "quantity": 1,
                    "amenity__label": "Desktop",
                    "amenity__icon": "Desktop",
                },
                {
                    "id": 126,
                    "quantity": 1,
                    "amenity__label": "Mouse and Keyboard",
                    "amenity__icon": "Keyboard & Mouse",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7478,
                    "name": "First Floor",
                    "type": 6,
                    "parent_id": 7476,
                },
                {
                    "id": 7476,
                    "name": "Meridian Towers",
                    "type": 5,
                    "parent_id": 7475,
                },
                {
                    "id": 7475,
                    "name": "Acme R&D Center - Springfield",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7702,
            "parent_id": 7479,
            "name": "Desk 112",
            "description": None,
            "type": 3,
            "tags": [
                {
                    "id": 352,
                    "name": "IT",
                    "description": "IT",
                }
            ],
            "venue_type": "desk",
            "amenities": [
                {
                    "id": 125,
                    "quantity": 1,
                    "amenity__label": "Desktop",
                    "amenity__icon": "Desktop",
                },
                {
                    "id": 133,
                    "quantity": 1,
                    "amenity__label": "Dual Monitors",
                    "amenity__icon": "Monitor",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7479,
                    "name": "Basement",
                    "type": 6,
                    "parent_id": 7476,
                },
                {
                    "id": 7476,
                    "name": "Meridian Towers",
                    "type": 5,
                    "parent_id": 7475,
                },
                {
                    "id": 7475,
                    "name": "Acme R&D Center - Springfield",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
        {
            "id": 7703,
            "parent_id": 7483,
            "name": "Desk 210",
            "description": None,
            "type": 3,
            "tags": [
                {
                    "id": 401,
                    "name": "Executive",
                    "description": "Executive",
                }
            ],
            "venue_type": "desk",
            "amenities": [
                {
                    "id": 126,
                    "quantity": 1,
                    "amenity__label": "Mouse and Keyboard",
                    "amenity__icon": "Keyboard & Mouse",
                },
                {
                    "id": 133,
                    "quantity": 1,
                    "amenity__label": "Dual Monitors",
                    "amenity__icon": "Monitor",
                },
                {
                    "id": 84,
                    "quantity": 1,
                    "amenity__label": "Wi-Fi",
                    "amenity__icon": "Wi-Fi",
                },
            ],
            "ancestors": [
                {
                    "id": 7483,
                    "name": "First Floor",
                    "type": 6,
                    "parent_id": 7482,
                },
                {
                    "id": 7482,
                    "name": "Harbor Tower",
                    "type": 5,
                    "parent_id": 7481,
                },
                {
                    "id": 7481,
                    "name": "Acme East Office - Rivertown",
                    "type": 4,
                    "parent_id": None,
                },
            ],
        },
    ],
    "get_resource_hierarchy": [
        {
            "id": 7481,
            "name": "Acme East Office - Rivertown",
            "parent_id": None,
            "type": 4,
            "city": "Dubai",
            "state": "Dubai",
            "country": "United Arab Emirates",
            "children": [
                {
                    "id": 7482,
                    "name": "Harbor Tower",
                    "parent_id": 7481,
                    "type": 5,
                    "city": "Dubai",
                    "state": "Dubai",
                    "country": "United Arab Emirates",
                    "children": [
                        {
                            "id": 7483,
                            "name": "First Floor",
                            "parent_id": 7482,
                            "type": 6,
                            "city": "Dubai",
                            "state": "Dubai",
                            "country": "United Arab Emirates",
                            "children": [],
                            "parents": [
                                {
                                    "id": 7481,
                                    "name": "Acme East Office - Rivertown",
                                },
                                {
                                    "id": 7482,
                                    "name": "Harbor Tower",
                                },
                            ],
                        },
                        {
                            "id": 7484,
                            "name": "Second Floor",
                            "parent_id": 7482,
                            "type": 6,
                            "city": "Dubai",
                            "state": "Dubai",
                            "country": "United Arab Emirates",
                            "children": [],
                            "parents": [
                                {
                                    "id": 7481,
                                    "name": "Acme East Office - Rivertown",
                                },
                                {
                                    "id": 7482,
                                    "name": "Harbor Tower",
                                },
                            ],
                        },
                    ],
                    "parents": [
                        {
                            "id": 7481,
                            "name": "Acme East Office - Rivertown",
                        }
                    ],
                }
            ],
            "parents": [],
        },
        {
            "id": 3570,
            "name": "Acme HQ Campus - Lakeside",
            "parent_id": None,
            "type": 4,
            "city": "Gurugram",
            "state": "Delhi (NCR)",
            "country": "India",
            "children": [
                {
                    "id": 3571,
                    "name": "Success Towers",
                    "parent_id": 3570,
                    "type": 5,
                    "city": "Gurugram",
                    "state": "Delhi (NCR)",
                    "country": "India",
                    "children": [
                        {
                            "id": 6597,
                            "name": "Basement",
                            "parent_id": 3571,
                            "type": 6,
                            "city": "Gurugram",
                            "state": "Delhi (NCR)",
                            "country": "India",
                            "children": [],
                            "parents": [
                                {
                                    "id": 3570,
                                    "name": "Acme HQ Campus - Lakeside",
                                },
                                {
                                    "id": 3571,
                                    "name": "Success Towers",
                                },
                            ],
                        },
                        {
                            "id": 3572,
                            "name": "First Floor",
                            "parent_id": 3571,
                            "type": 6,
                            "city": "Gurugram",
                            "state": "Delhi (NCR)",
                            "country": "India",
                            "children": [],
                            "parents": [
                                {
                                    "id": 3570,
                                    "name": "Acme HQ Campus - Lakeside",
                                },
                                {
                                    "id": 3571,
                                    "name": "Success Towers",
                                },
                            ],
                        },
                        {
                            "id": 7480,
                            "name": "Second Floor",
                            "parent_id": 3571,
                            "type": 6,
                            "city": "Gurugram",
                            "state": "Delhi (NCR)",
                            "country": "India",
                            "children": [],
                            "parents": [
                                {
                                    "id": 3570,
                                    "name": "Acme HQ Campus - Lakeside",
                                },
                                {
                                    "id": 3571,
                                    "name": "Success Towers",
                                },
                            ],
                        },
                        {
                            "id": 6598,
                            "name": "Third Floor",
                            "parent_id": 3571,
                            "type": 6,
                            "city": "Gurugram",
                            "state": "Delhi (NCR)",
                            "country": "India",
                            "children": [],
                            "parents": [
                                {
                                    "id": 3570,
                                    "name": "Acme HQ Campus - Lakeside",
                                },
                                {
                                    "id": 3571,
                                    "name": "Success Towers",
                                },
                            ],
                        },
                    ],
                    "parents": [
                        {
                            "id": 3570,
                            "name": "Acme HQ Campus - Lakeside",
                        }
                    ],
                }
            ],
            "parents": [],
        },
        {
            "id": 7475,
            "name": "Acme R&D Center - Springfield",
            "parent_id": None,
            "type": 4,
            "city": "Mumbai",
            "state": "Maharashtra",
            "country": "India",
            "children": [
                {
                    "id": 7476,
                    "name": "Meridian Towers",
                    "parent_id": 7475,
                    "type": 5,
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "country": "India",
                    "children": [
                        {
                            "id": 7479,
                            "name": "Basement",
                            "parent_id": 7476,
                            "type": 6,
                            "city": "Mumbai",
                            "state": "Maharashtra",
                            "country": "India",
                            "children": [],
                            "parents": [
                                {
                                    "id": 7475,
                                    "name": "Acme R&D Center - Springfield",
                                },
                                {
                                    "id": 7476,
                                    "name": "Meridian Towers",
                                },
                            ],
                        },
                        {
                            "id": 7478,
                            "name": "First Floor",
                            "parent_id": 7476,
                            "type": 6,
                            "city": "Mumbai",
                            "state": "Maharashtra",
                            "country": "India",
                            "children": [],
                            "parents": [
                                {
                                    "id": 7475,
                                    "name": "Acme R&D Center - Springfield",
                                },
                                {
                                    "id": 7476,
                                    "name": "Meridian Towers",
                                },
                            ],
                        },
                        {
                            "id": 7477,
                            "name": "Second Floor",
                            "parent_id": 7476,
                            "type": 6,
                            "city": "Mumbai",
                            "state": "Maharashtra",
                            "country": "India",
                            "children": [],
                            "parents": [
                                {
                                    "id": 7475,
                                    "name": "Acme R&D Center - Springfield",
                                },
                                {
                                    "id": 7476,
                                    "name": "Meridian Towers",
                                },
                            ],
                        },
                    ],
                    "parents": [
                        {
                            "id": 7475,
                            "name": "Acme R&D Center - Springfield",
                        }
                    ],
                }
            ],
            "parents": [],
        },
    ],
}


VMS_TOOL_RESPONSES = {
    "create_visitor_invite": {
        "invite_id": 232243,
        "venue_details": {"id": 7561, "latitude": 12.9420036, "longitude": 77.6083044},
    },
    "list_visitor_invites": {
        "next": None,
        "previous": None,
        "count": 1,
        "limit": 50,
        "results": [
            {
                "id": 232243,
                "url": "https://api.example.com/v4/get-pass/232243/",
                "host_id": 172096,
                "host": "Christopher Dias",
                "guest": "john doe",
                "valid_from": "2025-10-10T20:15:50.741000Z",
                "valid_till": "2025-10-10T22:15:50.741000Z",
                "duration": "2 hours",
                "venue_id": 7561,
                "venue": "Acme Gurugram",
                "status": "Expected",
                "created_at": "2025-10-10T20:11:25.411891Z",
                "modified_at": "2025-10-10T20:11:25.561163Z",
                "host_contacts": {
                    "email": "user@example.com",
                    "phone": "919920591423",
                },
                "guest_contacts": {"email": "john@mail.com"},
                "created_by": {
                    "name": "Christopher Dias",
                    "contacts": {
                        "email": "user@example.com",
                        "phone": "919920591423",
                    },
                    "member_unique_id": "user@example.com",
                },
                "host_as_member": {
                    "first_name": "Christopher",
                    "last_name": "Dias",
                    "contacts": {
                        "email": "user@example.com",
                        "phone": "919920591423",
                    },
                    "name": "Christopher Dias",
                    "member_unique_id": "user@example.com",
                    "designation": "new",
                    "contact_id": 455110,
                },
                "guest_as_member": {
                    "first_name": "john",
                    "last_name": "doe",
                    "contacts": {"email": "john@mail.com"},
                    "name": "john doe",
                    "contact_id": 455110,
                },
            }
        ],
    },
    "update_visitor_invite": {"invite_id": 232243},
    "cancel_visitor_invite": {"invite_id": 232243},
    "process_host_approval": {
        "id": 232243,
        "agenda": "Office visit",
        "host_as_member": {
            "name": "Christopher Dias",
            "designation": "new",
            "member_unique_id": "user@example.com",
        },
        "guest_as_member": {
            "name": "john doe",
            "designation": "consultant",
            "member_unique_id": "john.doe@example.com",
        },
        "venue": {
            "name": "Acme Gurugram",
            "description": "Corporate HQ campus",
            "address": {
                "city_name": "Gurugram",
                "city": "Gurugram",
                "state": "Delhi (NCR)",
                "country": "India",
                "address_line_1": "Success Towers, First Floor",
                "address_line_2": "DLF Cyber City",
                "timezone": "Asia/Kolkata",
            },
        },
        "hierarchy_invites_detail": {
            "0": {
                "meta": {
                    "deny_link": "https://api.example.com/v4/invites/232243/deny/",
                    "allow_link": "https://api.example.com/v4/invites/232243/allow/",
                    "allow_without_mobile_link": "https://api.example.com/v4/invites/232243/allow-without-mobile/",
                }
            }
        },
    },
}

MEMBER_TOOL_RESPONSE = {
    "get_member_by_email": {
        "id": 666,
        "first_name": "John",
        "last_name": "Doe",
        "contacts": {
            "email": "john.doe@example.com",
            "phone": "1234567890",
        },
        "name": "John Doe",
        "member_unique_id": "john.doe@example.com",
        "designation": "consultant",
        "contact_id": 455110,
    }
}

LATE_TRACKING_TOOL_RESPONSES = {
    "fetch_late_tracking_logs": {
        "next": None,
        "previous": None,
        "count": 1,
        "limit": 50,
        "results": [
            {
                "id": 98765,
                "visit_id": "512fab08-e1cd-4364-b0cd-3936e345c946",
                "venue_id": 3568,
                "venue_name": "Acme Gurugram",
                "member_details": {
                    "id": 2171953,
                    "contact_id": 1968744,
                    "name": "John Doe",
                    "department": "Product",
                    "contact_details": {
                        "email": "john.doe@example.com",
                        "phone": "9920591423",
                    },
                    "departure_time": "2025-07-02T09:31:19.006Z",
                    "arrival_time": None,
                    "eta": "15",
                    "eta_value_float": "15",
                    "old_eta": None,
                    "step_fn_eta": None,
                    "eta_timestamp": "2025-07-02T09:46:19.006Z",
                    "escalation_level": 2,
                    "home_address": "Sector 46, Gurugram",
                    "emergency_contacts": {
                        "name": "Raghav",
                        "email": "user2@example.com",
                        "phone": "918887020204",
                    },
                    "reporting_manager": None,
                    "security_contacts": None,
                    "hr_contacts": None,
                    "device_id": "93d97f81-cfd3-426d-825d-f27e3d1c2c7d",
                    "note": {},
                },
                "current_status": 3,
                "note": None,
            }
        ],
    },
    "update_late_tracking_log": {
        "id": 98765,
        "status": 2,
        "note": "Voice agent confirmed via call.",
        "arrival_time": "2025-10-31T06:41:15.000Z",
        "logged_at": "1730366475",
        "client_id": "guard-agent-poc",
    },
}

MOCK_TOOL_RESPONSES = {
    **MRM_TOOL_RESPONSES,
    **VMS_TOOL_RESPONSES,
    **LATE_TRACKING_TOOL_RESPONSES,
    **MEMBER_TOOL_RESPONSE,
}
